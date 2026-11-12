"""선별 품질 평가 (개발 도구, 운영 비포함).

시드 데이터로 채점을 돌려 결과를 표로 본다. config/interests.md나
pipeline/rank.py의 프롬프트를 고친 뒤 다시 돌려 비교하는 것이 튜닝 작업이다.

실행:
  python -m pipeline.evaluate                     # 시드에서 40건 표본
  python -m pipeline.evaluate --limit 80          # 표본 크기 변경
  python -m pipeline.evaluate --date 2026-11-12   # 특정 날짜 데이터로
"""

import argparse
import random
import statistics
import unicodedata
from collections import Counter, defaultdict

from pipeline.lib.config import load_interests, load_sources
from pipeline.lib.llm import AnthropicLLM
from pipeline.lib.secrets import require
from pipeline.lib.store import LocalStore
from pipeline.models import RankedItem, RawBundle, RawItem, ScoreItem
from pipeline.rank import rank
from pipeline.seed import SEED_DIR

# 고정 시드. 표본이 매번 달라지면 프롬프트 변경 효과를 분리할 수 없다.
SAMPLE_SEED = 20261110
DEFAULT_LIMIT = 40

# 한 소스가 표본에서 차지할 수 있는 최대 건수.
#
# 2026-11-12 실측: 시드 1923건을 균등 무작위로 40건 뽑으면 OpenAI_Blog가
# 18건(45%), Hugging_Face_Blog가 7건(17.5%)으로 **두 소스가 62.5%**를
# 차지하고 소스 45개 중 14개만 덮었다. 시드는 400일치라 발행이 잦은 소스가
# 누적으로 쌓인다(OpenAI 680건).
#
# 실제 운영에서 OpenAI는 240건 중 11건(4.6%)이다. 쏠린 표본으로 프로필을
# 튜닝하면 **OpenAI 공지문에 맞춰 기준을 깎게 된다.** 1이면 그 소스의
# 품질 분포를 볼 수 없으니 3으로 둔다.
PER_SOURCE_CAP = 3


def display_width(text: str) -> int:
    """터미널에서 차지하는 칸 수.

    한글·한자·일문은 두 칸을 차지하는데 `len()`은 1로 센다. 그대로 두면
    소스 열이 들쭉날쭉해서 표를 읽는 목적이 깨진다.
    """
    return sum(
        2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        for ch in text
    )


def pad(text: str, width: int) -> str:
    """표시 폭 기준으로 잘라 내고 공백을 채운다."""
    kept: list[str] = []
    used = 0
    for ch in text:
        step = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + step > width:
            break
        kept.append(ch)
        used += step
    return "".join(kept) + " " * (width - used)


def sample_items(items: list[RawItem], *, limit: int = DEFAULT_LIMIT) -> list[RawItem]:
    """재현 가능한 표본을 뽑는다. 한 소스가 독식하지 못하게 상한을 둔다."""
    # Random(seed)는 전역 난수 상태를 건드리지 않는 독립 생성기를 만든다.
    # random.sample을 직접 쓰면 다른 코드의 재현성에 영향을 준다.
    rng = random.Random(SAMPLE_SEED)

    소스별: dict[str, list[RawItem]] = defaultdict(list)
    for item in items:
        소스별[item.source].append(item)

    # 소스마다 상한까지만 남긴다. 소스 순서를 정렬해 두는 이유는 dict의
    # 삽입 순서가 입력에 따라 달라져 재현성이 흔들리기 때문이다.
    풀: list[RawItem] = []
    for 소스 in sorted(소스별):
        후보 = 소스별[소스]
        if len(후보) <= PER_SOURCE_CAP:
            풀.extend(후보)
        else:
            풀.extend(rng.sample(후보, PER_SOURCE_CAP))

    if len(풀) <= limit:
        return 풀
    return rng.sample(풀, limit)


def format_table(selected: list[RankedItem]) -> str:
    """선별 결과를 읽기 좋은 표로 만든다."""
    if not selected:
        return "(선별된 항목이 없다)"

    # 머리글도 pad로 맞춘다. f-string의 `{'점수':>4}`는 len() 기준이라
    # 한글 2자를 폭 4로 보지 않고 "  점수"(폭 6)를 만들어 데이터 행과 어긋난다.
    lines = [
        f"{pad('점수', 4)}  {pad('주제', 8)}  {pad('소스', 24)}  제목",
        "-" * 100,
    ]
    for item in selected:
        lines.append(
            f"{item.score:>4}  {pad(item.topic, 8)}  "
            f"{pad(item.item.source, 24)}  {item.item.title[:44]}"
        )
        lines.append(f"      └ {item.reason[:90]}")

    return "\n".join(lines)


def format_distribution(scores: list[ScoreItem]) -> str:
    """점수 분포. 쏠림이 보이면 프로필 기준이 모호하다는 뜻이다."""
    if not scores:
        return "(채점된 항목이 없다)"

    values = [s.score for s in scores]
    # 100점은 90 구간에 넣는다. (score // 10) * 10이면 100이 따로 떨어져
    # 구간이 하나 늘어난다.
    구간 = Counter(min(90, (v // 10) * 10) for v in values)

    최대 = max(구간.values())
    lines = []
    for 하한 in range(90, -1, -10):
        n = 구간.get(하한, 0)
        막대 = "█" * round(n / 최대 * 40) if n else ""
        # 상한 쪽은 자리를 채우지 않는다. 채우면 "90~ 99"가 되어 grep도,
        # 눈으로 읽기도 불편하다.
        lines.append(f"  {하한:3d}~{하한 + 9}  {n:4d}  {막대}")

    lines.append(
        f"  최고 {max(values)} · 최저 {min(values)} · "
        f"중앙값 {int(statistics.median(values))} · 평균 {statistics.mean(values):.1f}"
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="선별 품질 평가")
    parser.add_argument("--date", default=SEED_DIR,
                        help=f"데이터 디렉터리 (기본: {SEED_DIR})")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"표본 크기 (기본: {DEFAULT_LIMIT})")
    args = parser.parse_args()

    raw = LocalStore(date=args.date).read("raw", RawBundle)
    items = sample_items(raw.items, limit=args.limit)

    print(f"데이터: {args.date}  전체 {len(raw.items)}건 중 표본 {len(items)}건")
    집계 = Counter(item.source for item in items)
    print(f"  소스 {len(집계)}개 · 한 소스 최대 {max(집계.values())}건 "
          f"(상한 {PER_SOURCE_CAP})")
    print()

    bundle = rank(
        items=items,
        interests=load_interests(),
        recent_headlines=[],   # 평가에서는 중복 판정을 끈다
        weights={source.name: source.weight for source in load_sources()},
        llm=AnthropicLLM(require("ANTHROPIC_API_KEY")),
        window_start=raw.window_start,
        window_end=raw.window_end,
    )

    print("점수 분포 (가중치 적용 전)")
    print(format_distribution(bundle.all_scores))
    print()

    print(f"상위 {len(bundle.selected)}건")
    print(format_table(bundle.selected))
    print()

    # 하위권도 봐야 한다 — "왜 이게 떨어졌나"가 프롬프트 수정의 단서다.
    lowest = sorted(bundle.all_scores, key=lambda s: s.score)[:10]
    print("최하위 10건 (탈락 이유 확인용)")
    print("-" * 100)
    for score in lowest:
        item = items[score.index]
        print(f"{score.score:>4}  {pad(item.source, 24)}  {item.title[:44]}")
        print(f"      └ {score.reason[:90]}")


if __name__ == "__main__":
    main()
