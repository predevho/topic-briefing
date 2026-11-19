"""04 요약: 본문을 읽고 최종 선정과 요약을 한다.

02에서 이미 좁혔는데 또 거르는 이유는, 제목만으로는 알 수 없는 "본문을
읽어보니 내용이 없음"을 여기서 걸러내기 위해서다. 보도자료 재가공 기사가
대표적이다.

건수는 임계값으로 결정하고 상한만 둔다. LLM에 건수를 채우라고 하면
기준을 낮춰서 채우고, 그것이 반복되면 시스템이 버려진다.

실행: python -m pipeline.summarize
"""

import re
from datetime import datetime, timezone

from pipeline.enrich import BODY_MAX_CHARS
from pipeline.lib.llm import LLM, AnthropicLLM, Effort
from pipeline.lib.secrets import require
from pipeline.lib.store import LocalStore
from pipeline.lib.timeutil import KST
from pipeline.models import (
    HEADLINE_MAX,
    Article,
    ArticlesBundle,
    Briefing,
    Summary,
    SummarySheet,
)

# 가중치 적용 후 점수의 하한. 이 아래는 LLM이 넣었어도 보내지 않는다.
# `RankedItem.score`는 rank.apply_weight를 거친 값이므로 여기서 다시
# 가중치를 보지 않는다.
SCORE_THRESHOLD = 60

# 상한. 카톡에는 이 중 상위 5건만 싣고 나머지는 "외 N건"으로 표기한다.
MAX_SUMMARIES = 7

# 요약이 결과물 자체다. 채점(low)보다 한 단계 올린다.
SUMMARIZE_EFFORT: Effort = "medium"

# --- 출력 토큰 예산 ---
#
# Task 16과 같은 함정이다. 래퍼 기본값(16,000)에 맡기면 잘릴 수 있고,
# 잘리면 **브리핑 전체가** 날아간다(요약은 폴백이 없다).
#
# 채점과 달리 출력 **건수가 MAX_SUMMARIES로 묶여** 있어 입력 항목 수에
# 비례하지 않는다. 그래서 함수가 아니라 상수다. 대신 사고 토큰 여유를
# 크게 둔다 — 2026-11-18 실측으로 입력이 37,432토큰(기사 10건 본문)이고
# effort가 medium이라 사고가 길어질 수 있다.

# 요약 한 건당 출력 토큰. 헤드라인 30자 + 본문 요약 약 700~1,000자 + 의미 한
# 문장. 요점 3개이던 때는 실측 220토큰이었다(400으로 잡았다). 한국어 1,000자가
# 대략 700~900토큰이라 여유를 둔다(2026-11-19).
OUTPUT_TOKENS_PER_SUMMARY = 1_300

# 사고 토큰 여유. 비스트리밍 한계(21,333)를 넘기므로 래퍼가 스트리밍을
# 고른다 — Task 16에서 검증된 경로다.
THINKING_ALLOWANCE = 28_000

SUMMARIZE_MAX_TOKENS = THINKING_ALLOWANCE + MAX_SUMMARIES * OUTPUT_TOKENS_PER_SUMMARY


def shorten(text: str, limit: int = HEADLINE_MAX) -> str:
    """헤드라인을 상한 안으로 줄인다. 가능하면 단어 경계에서 끊는다.

    **왜 필요한가** — 2026-11-18 실측: 스키마에 `maxLength: 30`을 넣고
    프롬프트에도 "30자 이내"라고 적었는데 모델이 33자를 돌려줬다
    (`Cloudflare가 Raft 대신 QuePaxa를 고른 이유`). pydantic이 SummarySheet
    **전체**를 거부해 요약 7건이 한꺼번에 날아갔다.

    길이 보증은 프롬프트나 LLM이 아니라 여기에 있어야 한다. 한 건의 긴
    헤드라인으로 그날 브리핑을 잃을 이유가 없다.
    """
    text = text.strip()
    if len(text) <= limit:
        return text

    # 말줄임표 한 칸을 남긴다.
    cut = text[: limit - 1].rstrip()
    space = cut.rfind(" ")
    # 단어 경계가 너무 앞이면(절반 미만) 통째로 자르는 편이 낫다.
    if space >= limit // 2:
        cut = cut[:space].rstrip()
    return cut + "…"


# --- 잘린 끝 정리 (2026-11-20) ---
#
# 2026-11-20 실측: GeekNews 발췌가 `…남음 smo …`에서 끝났고, 모델이 잘린 "smo"를
# 보고 "smoltcp, DPDK, AF_XDP를 이용해"라고 썼다. DPDK·AF_XDP는 원문에 없다.
# 보지 못한 조각은 채울 수도 없으므로 **모델에게 보내기 전에** 정리한다.
# 저장된 원문(article_bodies)은 건드리지 않는다 — 여기서만 다듬는다.

# 원문이 잘렸다는 표시. 프롬프트 규칙이 이 표시를 가리킨다.
CUT_MARK = "[원문이 여기서 끊겼다]"

# 잘린 꼬리로 보는 조각: 공백 없는 영문·숫자·기호. "smo", "4.", "AF_X" 같은 것.
# 한국어 단어는 남긴다 — 메모체 발췌는 마지막 단어가 대개 완결돼 있다("않음").
_LATIN_FRAGMENT = re.compile(r"^[\x21-\x7e]+$")

# 문장 끝: 마침표·물음표·느낌표 뒤 공백, 또는 줄바꿈.
_SENTENCE_END = re.compile(r"[.!?。](?=\s)|\n")


def prepare_body(body: str) -> str:
    """모델에게 보낼 원문의 끝을 정리한다. 온전한 원문은 그대로 돌려준다.

    - 발췌가 `…`로 끝나면(GeekNews): 줄임표를 떼고, 그 앞이 잘린 영문·숫자
      조각이면 함께 뗀다. 버전 번호가 `4.`처럼 잘리면 모델이 버전을 지어낸다.
    - enrich가 BODY_MAX_CHARS에서 표시 없이 잘랐으면: 마지막 완결 문장까지
      되돌린다('consensus algorithms wou' 같은 꼬리를 남기지 않는다).
    - 둘 다 CUT_MARK를 붙여 모델이 잘린 글임을 알게 한다.
    """
    text = body.rstrip()

    if text.endswith(("…", "...")):
        text = text.rstrip(".…").rstrip()
        head, _, last = text.rpartition(" ")
        if head and _LATIN_FRAGMENT.match(last):
            text = head.rstrip(" ,;:")
        return f"{text} {CUT_MARK}"

    if len(body) >= BODY_MAX_CHARS:
        ends = [m.end() for m in _SENTENCE_END.finditer(text)]
        if ends:
            text = text[: ends[-1]].rstrip()
        else:
            text = text.rsplit(" ", 1)[0]
        return f"{text} {CUT_MARK}"

    return body


# 원문에 없는 영문 용어 점검. 도구·제품 이름을 지어내는 것이 가장 흔한 틀림이고
# (2026-11-20 DPDK·AF_XDP), 영문 토큰은 기계적으로 대조할 수 있다.
_TERM = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{2,}")


def unsupported_terms(overview: str, reference: str) -> list[str]:
    """요약에 나오지만 원문에 없는 영문 용어(3자 이상). 대소문자는 무시한다.

    `reference`는 모델이 본 것 — 본문에 **제목과 출처 이름**을 더해 넘긴다
    (2026-11-20 오탐: 'Simon Willison'은 출처 줄에서 본 이름이다).

    끝 글자 하나 차이는 있는 것으로 본다 — 복수·활용형(원문 'canaries' →
    요약 'canary', 2026-11-20 오탐). 지어낸 이름(DPDK, AF_XDP)은 그래도 걸린다.

    막지는 않는다 — 실행 로그에 찍어 사람이 볼 수 있게 한다. 원문이 한국어로
    쓴 것을 요약이 영문으로 옮긴 경우(예: '쿠버네티스' → 'Kubernetes')도 걸리므로
    판정이 아니라 단서다.
    """
    lowered = reference.lower()
    found: list[str] = []
    for term in _TERM.findall(overview):
        key = term.lower()
        if key in lowered or (len(key) >= 4 and key[:-1] in lowered):
            continue
        if term not in found:
            found.append(term)
    return found


def build_prompt(*, articles: list[Article]) -> str:
    """요약 프롬프트를 조립한다."""
    lines = [
        "아래 글들을 읽고, **보낼 가치가 있는 것만** 요약한다.",
        "",
        "## 규칙",
        "",
        f"- 최대 {MAX_SUMMARIES}건. **건수를 채우지 않는다.** 가치 있는 글이 2건이면 "
        "2건만 돌려준다. 억지로 채우면 기준이 무너진다.",
        "- 본문을 읽어보니 내용이 없는 글(보도자료 재가공, 제품 홍보, "
        "제목만 그럴듯한 글)은 **제외한다.**",
        f"- headline은 **{HEADLINE_MAX}자 이내**. 카카오톡 메시지 길이 제약이다.",
        "- overview는 **원문을 간추린 글**이다. 읽는 사람이 원문을 열지 않고도 흐름을 "
        "따라갈 수 있어야 한다. 사실을 나열하지 말고 문장을 이어서 쓴다.",
        "  - **2~3문단**, 문단 사이는 빈 줄. 문단마다 흐름의 한 단계를 맡는다 — "
        "① 배경·문제(왜 이 일을 했나) ② 무엇을·어떻게(접근과 핵심 내용) "
        "③ 결과·시사점(수치, 한계, 주의할 점).",
        "  - 원문이 넉넉하면 **700~1,000자**로 쓴다. 수치·고유명사·버전은 원문 그대로 옮긴다.",
        "  - **원문에 없는 내용은 쓰지 않는다.** 추측이나 일반론으로 길이를 채우지 않는다.",
        "  - 도구·제품·라이브러리 이름과 버전·수치는 **원문에 철자 그대로 있는 것만** 쓴다. "
        "배경지식으로 보충하지 않는다.",
        f"  - 원문 끝의 '{CUT_MARK}'는 글이 거기서 잘렸다는 뜻이다. "
        "**잘린 단어를 추측해 완성하지 않는다.**",
        "  - '(발췌 — 원문이 짧다)' 표시가 붙은 글은 받은 원문이 짧은 발췌뿐이다. "
        "**원문보다 길게 쓰지 않는다** — 1~2문단으로 원문에 있는 만큼만 쓴다.",
        "- why_it_matters는 한 문장. '이게 왜 중요한가'를 백엔드 개발자 관점에서 쓴다. "
        "overview를 반복하지 말고 의미만 말한다.",
        "- **모든 출력은 한국어로 쓴다.** 원문이 영어여도 한국어로 요약한다.",
        "- 고유명사(제품명, 회사명, 기술명)는 원어를 그대로 쓴다.",
        "- index에는 각 글의 [번호]를 쓴다. 제외한 글은 응답에 넣지 않는다.",
        "",
        "## 글",
        "",
    ]

    for index, article in enumerate(articles):
        item = article.ranked.item
        # 본문을 여기서 다시 자르지 않는다. enrich가 BODY_MAX_CHARS로 이미
        # 잘랐고, 손잡이가 두 곳이면 토큰 예산을 추적할 수 없다.
        # 발췌로만 받은 글은 모델에게 알린다. 모르면 짧은 원문을 길게 늘리려고
        # 지어낸다(2026-11-19 설계). GeekNews 글이 늘 이렇다.
        excerpt = " (발췌 — 원문이 짧다)" if article.body_source == "rss_excerpt" else ""
        lines += [
            f"### [{index}] {item.title}{excerpt}",
            f"출처: {item.source}  /  주제: {article.ranked.topic}",
            "",
            # 잘린 끝을 정리해서 보낸다(prepare_body). 저장된 원문은 그대로다.
            prepare_body(article.body),
            "",
            "---",
            "",
        ]

    return "\n".join(lines)


def summarize(*, articles: ArticlesBundle, llm: LLM) -> Briefing:
    """최종 선정과 요약. 0건도 정상 결과다."""
    candidates = articles.articles

    if not candidates:
        return Briefing(
            window_start=articles.window_start,
            window_end=articles.window_end,
            summaries=[],
            considered=0,
        )

    prompt = build_prompt(articles=candidates)
    # 재시도는 llm.parse 안에서 끝난다 (rank.py와 같은 이유).
    sheet, tokens = llm.parse(
        prompt=prompt,
        output_format=SummarySheet,
        effort=SUMMARIZE_EFFORT,
        max_tokens=SUMMARIZE_MAX_TOKENS,
    )

    summaries: list[Summary] = []
    seen: set[int] = set()

    for draft in sheet.summaries:
        # 범위 밖 번호나 중복 번호를 돌려줄 수 있다. 둘 다 무시하고,
        # 중복은 먼저 나온 것을 쓴다.
        if not (0 <= draft.index < len(candidates)) or draft.index in seen:
            continue
        seen.add(draft.index)

        article = candidates[draft.index]

        # 결정적 가드: LLM 판단과 별개로 점수 하한을 적용한다.
        if article.ranked.score < SCORE_THRESHOLD:
            continue

        # 빈 요약은 요약이 아니다. 스키마에서 거부하면 시트 **전체**가 날아가므로
        # 여기서 그 한 건만 거른다.
        overview = draft.overview.strip()
        if not overview:
            continue

        summaries.append(Summary(
            article=article,
            # LLM이 상한을 넘겨도 브리핑을 잃지 않는다. shorten 설명 참조.
            headline=shorten(draft.headline),
            overview=overview,
            why_it_matters=draft.why_it_matters,
        ))

    # 상한을 넘으면 점수 높은 것부터 남긴다.
    summaries.sort(key=lambda s: s.article.ranked.score, reverse=True)

    return Briefing(
        window_start=articles.window_start,
        window_end=articles.window_end,
        summaries=summaries[:MAX_SUMMARIES],
        considered=len(candidates),
        tokens=tokens,
    )


def main() -> None:
    date = datetime.now(timezone.utc).astimezone(KST).date().isoformat()
    store = LocalStore(date=date)

    briefing = summarize(
        articles=store.read("articles", ArticlesBundle),
        llm=AnthropicLLM(require("ANTHROPIC_API_KEY")),
    )
    path = store.write("briefing", briefing)

    print(f"요약 {len(briefing.summaries)}건 / 후보 {briefing.considered}건 → {path}")
    if not briefing.summaries:
        print("  보낼 만한 글이 없다. 이것도 정상 결과다.")

    # 줄인 건수를 센다. 자주 나오면 프롬프트의 "30자 이내"가 안 먹히는
    # 것이고, HEADLINE_MAX 자체를 다시 볼 근거가 된다.
    줄임 = sum(1 for s in briefing.summaries if s.headline.endswith("…"))
    if 줄임:
        print(f"  헤드라인 {줄임}건을 {HEADLINE_MAX}자로 줄였다 "
              f"(프롬프트 지시가 안 먹힌 것이다. 반복되면 상한을 다시 본다)")
    print()
    for summary in briefing.summaries:
        article = summary.article
        mark = "발췌" if article.body_source == "rss_excerpt" else "본문"
        print(f"  {article.ranked.score:3d}  [{mark}] {summary.headline}")
        print(f"       {len(summary.overview or '')}자 · {(summary.overview or '')[:70]}")
        # 원문에 없는 영문 용어 — 지어내기의 단서(2026-11-20 DPDK·AF_XDP).
        item = article.ranked.item
        reference = f"{item.title} {item.source} {article.body}"
        if extra := unsupported_terms(summary.overview or "", reference):
            print(f"       ⚠ 원문에 없는 영문 용어: {', '.join(extra)}")
        print(f"       → {summary.why_it_matters[:70]}")
        print()


if __name__ == "__main__":
    main()
