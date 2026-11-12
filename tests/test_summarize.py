import pytest
from pydantic import ValidationError

from pipeline.lib.llm import needs_streaming
from pipeline.models import (
    HEADLINE_MAX,
    Article,
    ArticlesBundle,
    RankedItem,
    RawItem,
    SummaryDraft,
    SummarySheet,
)
from pipeline.summarize import (
    MAX_SUMMARIES,
    OUTPUT_TOKENS_PER_SUMMARY,
    SCORE_THRESHOLD,
    SUMMARIZE_EFFORT,
    SUMMARIZE_MAX_TOKENS,
    THINKING_ALLOWANCE,
    build_prompt,
    shorten,
    summarize,
)
from tests.fakes import FakeLLM

WINDOW = ("2026-11-09T22:20:00+00:00", "2026-11-10T22:20:00+00:00")


def _article(index: int = 0, score: int = 85, source: str = "토스_기술블로그") -> Article:
    return Article(
        ranked=RankedItem(
            item=RawItem(
                source=source,
                title=f"제목 {index}",
                url=f"https://e.com/{index}",
                published="2026-11-10T05:30:00+00:00",
                excerpt="발췌",
            ),
            score=score,
            reason="이유",
            topic="backend",
        ),
        body=f"본문 {index}",
        body_source="trafilatura",
    )


def _bundle(articles) -> ArticlesBundle:
    return ArticlesBundle(
        window_start=WINDOW[0], window_end=WINDOW[1], articles=articles
    )


def _draft(index: int) -> SummaryDraft:
    return SummaryDraft(
        index=index,
        headline=f"헤드라인 {index}",
        bullets=["요점 하나", "요점 둘"],
        why_it_matters="중요한 이유",
    )


def _summarize(articles, drafts):
    llm = FakeLLM(responses=[SummarySheet(summaries=drafts)])
    return summarize(articles=_bundle(articles), llm=llm), llm


# --- 출력 토큰 예산 ---
#
# Task 16과 같은 함정이다. 래퍼 기본값(16,000)에 맡기면 잘릴 수 있고, 잘리면
# 브리핑 전체가 날아간다. 여기서는 출력 **건수**가 MAX_SUMMARIES로 묶여 있어
# 항목 수에 비례하지 않으므로 상수로 둔다 — 대신 사고 토큰 여유가 커야 한다.
# 2026-11-18 실측: 입력이 37,432토큰(기사 10건 본문)이고 effort는 medium이다.

def test_요약_출력_예산이_기본값보다_크다():
    from pipeline.lib.llm import DEFAULT_MAX_TOKENS

    assert SUMMARIZE_MAX_TOKENS > DEFAULT_MAX_TOKENS


def test_최대_건수를_담을_수_있다():
    assert SUMMARIZE_MAX_TOKENS >= THINKING_ALLOWANCE + MAX_SUMMARIES * OUTPUT_TOKENS_PER_SUMMARY


def test_사고_토큰_여유가_넉넉하다():
    """effort=medium에 입력 37k 토큰이다. 사고가 길어질 수 있다."""
    assert THINKING_ALLOWANCE >= 16_000


def test_요약은_스트리밍으로_간다():
    """예산이 비스트리밍 한계(21,333)를 넘는다. 래퍼가 알아서 고른다."""
    assert needs_streaming(SUMMARIZE_MAX_TOKENS)


def test_산정한_max_tokens를_LLM에_넘긴다():
    """계산만 하고 넘기지 않으면 아무 의미가 없다."""
    _, llm = _summarize([_article(0)], [_draft(0)])
    assert llm.calls[0]["max_tokens"] == SUMMARIZE_MAX_TOKENS


def test_요약은_medium_effort로_한다():
    """채점은 low, 요약은 medium. 요약이 결과물 자체다."""
    _, llm = _summarize([_article(0)], [_draft(0)])
    assert llm.calls[0]["effort"] == SUMMARIZE_EFFORT == "medium"


# --- 계약 경계 ---

def test_초안_헤드라인에는_상한을_걸지_않는다():
    """**스키마의 maxLength는 강제되지 않는다 — 2026-11-18 실측.**

    `maxLength: 30`을 넣고 프롬프트에도 "30자 이내"라고 적었는데 모델이
    33자를 돌려줬고(`Cloudflare가 Raft 대신 QuePaxa를 고른 이유`),
    pydantic이 SummarySheet **전체**를 거부해 요약 7건이 한꺼번에 날아갔다.

    LLM 출력은 신뢰할 수 없는 입력이다. 상한은 받는 쪽(Summary)에 두고
    중간에서 줄인다.
    """
    schema = SummarySheet.model_json_schema()["$defs"]["SummaryDraft"]
    assert "maxLength" not in schema["properties"]["headline"]

    # 긴 헤드라인도 받아들여야 한다 — 거부하면 브리핑 전체를 잃는다
    draft = SummaryDraft(index=0, headline="가" * 40,
                         bullets=["b"], why_it_matters="w")
    assert len(draft.headline) == 40


def test_불릿_개수가_스키마에_들어간다():
    schema = SummarySheet.model_json_schema()["$defs"]["SummaryDraft"]
    assert schema["properties"]["bullets"]["maxItems"] == 3
    assert schema["properties"]["bullets"]["minItems"] == 1


def test_최종_요약은_헤드라인_상한을_지킨다():
    """DB의 `articles_headline_len` 제약과 같은 값이다."""
    from pipeline.models import Summary

    with pytest.raises(ValidationError):
        Summary(article=_article(), headline="가" * (HEADLINE_MAX + 1),
                bullets=["b"], why_it_matters="w")


def test_빈_헤드라인을_거부한다():
    with pytest.raises(ValidationError):
        SummaryDraft(index=0, headline="", bullets=["b"], why_it_matters="w")


def test_불릿이_없으면_거부한다():
    """요점이 없는 요약은 요약이 아니다."""
    with pytest.raises(ValidationError):
        SummaryDraft(index=0, headline="h", bullets=[], why_it_matters="w")


# --- 프롬프트 ---

def test_프롬프트에_본문이_들어간다():
    prompt = build_prompt(articles=[_article()])
    assert "본문 0" in prompt


def test_프롬프트가_본문을_다시_자르지_않는다():
    """enrich가 이미 BODY_MAX_CHARS로 잘랐다. 여기서 또 자르면 손잡이가
    두 곳이 되어 토큰 예산을 추적할 수 없다.
    """
    긴본문 = "가" * 8000
    article = Article(
        ranked=_article().ranked, body=긴본문, body_source="trafilatura",
    )
    assert 긴본문 in build_prompt(articles=[article])


def test_프롬프트가_한국어_요약을_요구한다():
    """해외 소스가 영어로 요약되면 안 된다."""
    prompt = build_prompt(articles=[_article()])
    assert "한국어" in prompt


def test_프롬프트가_헤드라인_길이_제약을_명시한다():
    prompt = build_prompt(articles=[_article()])
    assert "30자" in prompt


def test_프롬프트가_건수를_채우지_말라고_지시한다():
    """건수 채우기가 큐레이션을 망치는 주된 방식이다."""
    prompt = build_prompt(articles=[_article()])
    assert "채우지" in prompt


def test_프롬프트가_최대_건수를_명시한다():
    prompt = build_prompt(articles=[_article()])
    assert str(MAX_SUMMARIES) in prompt


def test_프롬프트에_출처와_주제가_들어간다():
    """요약이 "토스가 공개한"처럼 출처를 쓸 수 있어야 한다."""
    prompt = build_prompt(articles=[_article(0, source="토스_기술블로그")])
    assert "토스_기술블로그" in prompt and "backend" in prompt


def test_프롬프트에_번호가_들어간다():
    prompt = build_prompt(articles=[_article(0), _article(1)])
    assert "[0]" in prompt and "[1]" in prompt


# --- 요약 ---

def test_LLM이_돌려준_요약을_담는다():
    briefing, _ = _summarize([_article(0)], [_draft(0)])

    assert len(briefing.summaries) == 1
    assert briefing.summaries[0].headline == "헤드라인 0"


def test_LLM이_생략한_건은_빠진다():
    """본문을 읽어보니 내용이 없는 글을 여기서 걸러낸다."""
    briefing, _ = _summarize([_article(0), _article(1)], [_draft(0)])

    assert len(briefing.summaries) == 1
    assert briefing.summaries[0].article.ranked.item.title == "제목 0"


def test_임계값_미달은_LLM이_넣었어도_제외한다():
    """결정적 가드. LLM 판단과 무관하게 점수 기준을 적용한다."""
    low = _article(0, score=SCORE_THRESHOLD - 1)
    briefing, _ = _summarize([low], [_draft(0)])

    assert briefing.summaries == []


def test_임계값과_같으면_통과한다():
    exact = _article(0, score=SCORE_THRESHOLD)
    briefing, _ = _summarize([exact], [_draft(0)])

    assert len(briefing.summaries) == 1


def test_최대_건수를_넘지_않는다():
    articles = [_article(i) for i in range(MAX_SUMMARIES + 3)]
    drafts = [_draft(i) for i in range(MAX_SUMMARIES + 3)]
    briefing, _ = _summarize(articles, drafts)

    assert len(briefing.summaries) == MAX_SUMMARIES


def test_점수_높은_순으로_남긴다():
    """상한을 넘으면 점수가 높은 것이 남아야 한다."""
    articles = [_article(i, score=60 + i) for i in range(MAX_SUMMARIES + 2)]
    drafts = [_draft(i) for i in range(MAX_SUMMARIES + 2)]
    briefing, _ = _summarize(articles, drafts)

    scores = [s.article.ranked.score for s in briefing.summaries]
    assert scores == sorted(scores, reverse=True)
    assert min(scores) > 60


def test_범위를_벗어난_index는_무시한다():
    briefing, _ = _summarize([_article(0)], [_draft(0), _draft(99)])
    assert len(briefing.summaries) == 1


def test_중복_index는_한_번만_담는다():
    briefing, _ = _summarize([_article(0)], [_draft(0), _draft(0)])
    assert len(briefing.summaries) == 1


def test_중복_index는_먼저_나온_것을_쓴다():
    """어느 쪽을 쓰는지가 정해져 있어야 한다."""
    첫째 = SummaryDraft(index=0, headline="먼저", bullets=["b"], why_it_matters="w")
    둘째 = SummaryDraft(index=0, headline="나중", bullets=["b"], why_it_matters="w")
    briefing, _ = _summarize([_article(0)], [첫째, 둘째])

    assert briefing.summaries[0].headline == "먼저"


def test_후보_건수를_기록한다():
    """적중률 추적에 쓴다."""
    briefing, _ = _summarize([_article(0), _article(1)], [_draft(0)])
    assert briefing.considered == 2


def test_본문이_없으면_LLM을_호출하지_않는다():
    llm = FakeLLM(responses=[])
    briefing = summarize(articles=_bundle([]), llm=llm)

    assert briefing.summaries == []
    assert llm.prompts == []
    assert briefing.considered == 0


def test_전부_임계값_미달이면_빈_브리핑이_된다():
    """0건이 정상 상태다. 예외를 던지지 않는다."""
    low = [_article(i, score=10) for i in range(3)]
    briefing, _ = _summarize(low, [_draft(0), _draft(1), _draft(2)])

    assert briefing.summaries == []
    assert briefing.considered == 3


def test_윈도우_경계를_이어받는다():
    briefing, _ = _summarize([_article(0)], [_draft(0)])
    assert briefing.window_start == WINDOW[0]
    assert briefing.window_end == WINDOW[1]


def test_임계값이_가중치_적용_후_점수에_걸린다():
    """`RankedItem.score`는 이미 가중치가 적용된 값이다(rank.apply_weight).
    원점수에 걸면 가중치가 무의미해진다.
    """
    # 원점수 50에 가중치 1.3을 적용하면 65 — 임계값 60을 넘는다.
    # rank가 그 계산을 끝내 놓으므로 여기서는 65를 그대로 본다.
    article = _article(0, score=65)
    briefing, _ = _summarize([article], [_draft(0)])

    assert len(briefing.summaries) == 1


# --- 헤드라인 줄이기 ---
#
# 2026-11-18 실측으로 생긴 기능이다. 스키마의 maxLength는 강제되지 않고,
# 한 건이 넘기면 pydantic이 SummarySheet 전체를 거부해 브리핑이 사라진다.

def test_상한_안이면_그대로_둔다():
    assert shorten("짧은 헤드라인") == "짧은 헤드라인"


def test_상한을_넘으면_줄인다():
    assert len(shorten("가" * 50)) <= HEADLINE_MAX


def test_줄이면_말줄임표를_붙인다():
    assert shorten("가" * 50).endswith("…")


def test_단어_경계에서_끊는다():
    """한글도 띄어쓰기가 있다. 단어 중간에서 끊기면 읽기 나쁘다."""
    원문 = "Cloudflare가 Raft 대신 QuePaxa를 고른 이유"
    결과 = shorten(원문)

    assert len(결과) <= HEADLINE_MAX
    assert 결과.endswith("…")
    assert "QuePax" not in 결과 or 결과.startswith("Cloudflare가 Raft 대신 QuePaxa")


def test_단어_경계가_너무_앞이면_통째로_자른다():
    """공백이 맨 앞에만 있으면 단어 경계를 따르면 거의 다 날아간다."""
    원문 = "가 " + "나" * 50
    결과 = shorten(원문)

    assert len(결과) <= HEADLINE_MAX
    assert len(결과) > HEADLINE_MAX // 2


def test_앞뒤_공백을_없앤다():
    assert shorten("  헤드라인  ") == "헤드라인"


def test_긴_헤드라인이_와도_브리핑을_잃지_않는다():
    """이게 이 기능의 존재 이유다. 한 건 때문에 7건을 잃지 않는다."""
    drafts = [
        SummaryDraft(index=0, headline="짧다", bullets=["b"], why_it_matters="w"),
        SummaryDraft(index=1, headline="가" * 40, bullets=["b"], why_it_matters="w"),
    ]
    briefing, _ = _summarize([_article(0), _article(1)], drafts)

    assert len(briefing.summaries) == 2
    assert all(len(s.headline) <= HEADLINE_MAX for s in briefing.summaries)
