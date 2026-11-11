"""02 선별: 수집 항목을 한 번의 LLM 호출로 채점하고 상위 N건을 고른다.

건당 호출하지 않는 이유는, 한 번에 넣어야 LLM이 "이 둘은 같은 사건이니
하나만" 같은 교차 판단을 할 수 있기 때문이다.

실행: python -m pipeline.rank
"""

from datetime import datetime, timezone

from pipeline.lib.config import load_interests, load_sources
from pipeline.lib.llm import LLM, AnthropicLLM, Effort, TruncatedError
from pipeline.lib.secrets import require
from pipeline.lib.store import LocalStore, SupabaseStore
from pipeline.lib.timeutil import KST
from pipeline.models import (
    RankedBundle,
    RankedItem,
    RawBundle,
    RawItem,
    ScoreItem,
    ScoreSheet,
)

# 본문을 가져올 건수. 03_enrich가 이 개수만 크롤링한다.
TOP_N = 10

# 같은 사건 중복 판정에 참고할 과거 범위.
DEDUP_LOOKBACK_DAYS = 14

# 채점은 깊은 추론이 필요 없다. 토큰을 아낀다.
RANK_EFFORT: Effort = "low"

# 발췌를 자르는 길이. 그 이상은 채점 정확도에 기여하지 않으면서 토큰만
# 늘린다(항목 수가 많으므로 누적이 크다).
EXCERPT_CHARS = 400

# --- 출력 토큰 산정 ---
#
# 2026-11-12 실측: 227건(96시간 윈도우의 현실적 상한)을 한 프롬프트에 넣으면
# 입력 42,135토큰이고, ScoreItem 한 건이 JSON으로 82토큰이라 출력은
# 18,614토큰이 필요하다. **래퍼의 기본값 16,000으로는 잘린다.**
#
# 잘리면 stop_reason=max_tokens로 오고, 재시도해도 똑같이 잘린다. 그래서
# 기본값에 맡기지 않고 항목 수에서 계산해 넘긴다.

# 실측 82토큰에 여유를 둔다. 이유 문장이 길어질 수 있다.
OUTPUT_TOKENS_PER_ITEM = 110

# Opus 5.5는 사고가 항상 켜져 있고(끌 수 없다), 사고 토큰도 max_tokens에
# 포함된다. effort=low라 많지는 않지만 0은 아니다.
THINKING_ALLOWANCE = 8_000

# 비스트리밍으로 안전하게 받을 수 있는 상한. 이보다 크게 받으려면 스트리밍이
# 필요하다. 지금 여유는 약 363건이고 실측 상한이 227건이라 한동안 버틴다
# (test_현실적_상한에_여유가_남아_있다가 지킨다).
MAX_OUTPUT_TOKENS = 48_000


def weighted_score(score: int, weight: float) -> float:
    """상한 없는 가중 점수. **정렬에만** 쓴다.

    왜 상한 없는 값이 따로 필요한가 — 2026-11-12 실측:
    상위권이 전부 100점으로 묶여 순서가 사라졌다.

        원 90 ×1.3 = 117.0 → 100
        원 85 ×1.3 = 110.5 → 100
        원 88 ×1.2 = 105.6 → 100
        원 85 ×1.2 = 102.0 → 100

    LLM 원점수는 잘 퍼져 있었다(최고 92, 중앙값 30). **100점 쏠림은
    우리 상한이 만든 것**이고, 하필 상위 10건을 고르는 자리에서 생겼다.
    정렬은 상한 없는 값으로, 표시·저장은 상한 있는 값으로 한다.
    """
    return score * weight


def apply_weight(score: int, weight: float) -> int:
    """표시·저장용 가중 점수. 상한 100.

    `score`의 계약이 0~100이고 DB 제약도 같다. 120점을 보여 줄 수는 없다.
    """
    return min(100, round(score * weight))


def rank_max_tokens(item_count: int) -> int:
    """항목 수에 맞춘 출력 상한."""
    return min(
        MAX_OUTPUT_TOKENS,
        THINKING_ALLOWANCE + item_count * OUTPUT_TOKENS_PER_ITEM,
    )


def max_items_per_call() -> int:
    """한 번에 채점할 수 있는 항목 수의 상한."""
    return (MAX_OUTPUT_TOKENS - THINKING_ALLOWANCE) // OUTPUT_TOKENS_PER_ITEM


def build_prompt(
    *,
    interests: str,
    recent_headlines: list[str],
    items: list[RawItem],
) -> str:
    """채점 프롬프트를 조립한다."""
    lines = [
        "당신은 아래 '관심사 프로필'을 가진 사람의 큐레이터다.",
        "각 글을 0~100점으로 채점하고, 점수를 준 이유를 한 문장으로 쓴다.",
        "topic은 AI / backend / infra / tooling / other 중 하나로 분류한다.",
        "",
        # 빠뜨린 항목은 순위에 들어올 수 없다 — 조용히 버려진다. 그래서
        # 건수를 명시해 전부 채점하라고 말한다.
        f"글이 {len(items)}개 있다. **{len(items)}개 전부에 점수를 매긴다.** "
        f"낮은 점수를 줄 글도 빠뜨리지 않는다.",
        "",
        "## 관심사 프로필",
        "",
        interests,
    ]

    if recent_headlines:
        lines += [
            "",
            f"## 최근 발행한 헤드라인 (최근 {DEDUP_LOOKBACK_DAYS}일)",
            "",
            "아래와 같은 사건·주제를 다룬 글은 40점 이하로 내린다.",
            "단, 명시적인 후속편은 중복이 아니다.",
            "",
        ]
        lines += [f"- {headline}" for headline in recent_headlines]

    lines += [
        "",
        "## 채점할 글",
        "",
        "각 글은 [번호]로 참조한다. 응답의 index에 그 번호를 쓴다.",
        "",
    ]
    for index, item in enumerate(items):
        lines += [
            f"[{index}] ({item.source}) {item.title}",
            f"      {item.excerpt[:EXCERPT_CHARS]}",
            "",
        ]

    return "\n".join(lines)


def rank(
    *,
    items: list[RawItem],
    interests: str,
    recent_headlines: list[str],
    weights: dict[str, float],
    llm: LLM,
    window_start: str,
    window_end: str,
) -> RankedBundle:
    """채점하고 상위 TOP_N건을 고른다."""
    if not items:
        # 수집이 0건이면 호출할 이유가 없다. 토큰을 쓰지 않는다.
        return RankedBundle(
            window_start=window_start,
            window_end=window_end,
            selected=[],
            all_scores=[],
        )

    # 호출 전에 막는다. 보내 놓고 잘리면 토큰을 쓰고도 결과가 없다.
    한계 = max_items_per_call()
    if len(items) > 한계:
        raise TruncatedError(
            f"항목이 {len(items)}건인데 한 번에 채점할 수 있는 상한은 {한계}건이다. "
            f"보내면 출력이 max_tokens에 걸려 잘리고, 재시도해도 같다. "
            f"소스를 줄이거나, 여러 번에 나눠 채점하도록 고치거나, "
            f"스트리밍을 도입해 MAX_OUTPUT_TOKENS를 올린다."
        )

    prompt = build_prompt(
        interests=interests, recent_headlines=recent_headlines, items=items
    )

    # 재시도는 llm.parse 안에서 끝난다 — 전송 계층은 SDK가, 스키마 실패는
    # 래퍼가 1회 담당한다. 여기서 또 감싸면 이중 재시도가 된다.
    sheet, _tokens = llm.parse(
        prompt=prompt,
        output_format=ScoreSheet,
        effort=RANK_EFFORT,
        max_tokens=rank_max_tokens(len(items)),
    )

    # (정렬 기준, 항목) 쌍으로 모은다. 정렬 기준은 상한 없는 값이고
    # 항목에 담기는 점수는 상한 있는 값이다 — weighted_score의 설명 참조.
    scored: list[tuple[float, RankedItem]] = []
    seen_indexes: set[int] = set()
    kept_scores: list[ScoreItem] = []

    for score in sheet.scores:
        # LLM이 범위 밖 번호나 중복 번호를 돌려줄 수 있다. 둘 다 무시한다.
        # (음수는 ScoreItem의 ge=0이 계약 경계에서 막는다.)
        if not (0 <= score.index < len(items)) or score.index in seen_indexes:
            continue
        seen_indexes.add(score.index)

        item = items[score.index]
        weight = weights.get(item.source, 1.0)

        kept_scores.append(score)
        scored.append((
            weighted_score(score.score, weight),
            RankedItem(
                item=item,
                score=apply_weight(score.score, weight),
                reason=score.reason,
                topic=score.topic,
            ),
        ))

    # 상한 없는 값으로 정렬한다. 상한 있는 값으로 정렬하면 100에 묶인
    # 항목들의 순서가 입력 순서로 결정돼 버린다.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    ranked = [item for _, item in scored]

    return RankedBundle(
        window_start=window_start,
        window_end=window_end,
        selected=ranked[:TOP_N],
        all_scores=kept_scores,
        # 정렬했으므로 첫 항목이 최고 점수다. 0건이면 None으로 둔다 —
        # 0으로 두면 "최고 0점"과 "수집 없음"이 구분되지 않는다.
        # 상한 있는 값을 쓴다 — 0건인 날 화면이 "최고 117점"이면 안 된다.
        max_score=ranked[0].score if ranked else None,
    )


def main() -> None:
    date = datetime.now(timezone.utc).astimezone(KST).date().isoformat()
    store = LocalStore(date=date)
    raw = store.read("raw", RawBundle)

    remote = SupabaseStore(require("SUPABASE_URL"), require("SUPABASE_SECRET_KEY"))
    weights = {source.name: source.weight for source in load_sources()}

    bundle = rank(
        items=raw.items,
        interests=load_interests(),
        recent_headlines=remote.recent_headlines(days=DEDUP_LOOKBACK_DAYS),
        weights=weights,
        llm=AnthropicLLM(require("ANTHROPIC_API_KEY")),
        window_start=raw.window_start,
        window_end=raw.window_end,
    )

    path = store.write("ranked", bundle)

    # 수집과 채점 건수를 함께 낸다. LLM이 일부를 빼먹으면 그 항목은 순위에
    # 들어올 수 없는데, 한쪽만 보면 누락이 드러나지 않는다.
    누락 = len(raw.items) - len(bundle.all_scores)
    print(f"수집 {len(raw.items)}건 → 채점 {len(bundle.all_scores)}건"
          f"{f' (누락 {누락}건)' if 누락 else ''} → 선별 {len(bundle.selected)}건")
    print(f"  → {path}")
    if 누락:
        print(f"  [주의] {누락}건이 채점되지 않았다. 프롬프트가 전부 채점하라고 "
              f"말하는데도 빠졌다면 항목 수를 줄이는 것을 검토한다.")
    print()
    for item in bundle.selected:
        print(f"  {item.score:3d}  [{item.topic}] {item.item.title[:50]}")
        print(f"       {item.reason[:70]}")


if __name__ == "__main__":
    main()
