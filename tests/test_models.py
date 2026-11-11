import pytest
from pydantic import ValidationError

from pipeline.models import (
    Article,
    ArticlesBundle,
    Briefing,
    RankedBundle,
    RankedItem,
    RawBundle,
    RawItem,
    ScoreItem,
    ScoreSheet,
    SourceError,
    Summary,
)


def _raw() -> RawItem:
    return RawItem(
        source="토스_기술블로그",
        title="결제 서버 P99 40ms 달성기",
        url="https://toss.tech/article/payment-latency",
        published="2026-11-10T05:30:00+00:00",
        excerpt="지연의 원인을 추적한 과정을 정리했다.",
    )


def test_RawItem이_JSON_왕복을_견딘다():
    item = _raw()
    restored = RawItem.model_validate(item.model_dump())
    assert restored == item


def test_모델이_불변이다():
    """단계 간 데이터는 중간에 바뀌면 안 된다."""
    item = _raw()
    with pytest.raises(ValidationError):
        item.title = "다른 제목"


def test_정의되지_않은_필드를_거부한다():
    """오타난 키가 조용히 통과하면 다음 단계에서 터진다."""
    with pytest.raises(ValidationError):
        RawItem(
            source="s", title="t", url="u", published="p", excerpt="e",
            titel="오타",
        )


def test_점수는_0에서_100_사이여야_한다():
    with pytest.raises(ValidationError):
        ScoreItem(index=0, score=101, reason="r", topic="AI")
    with pytest.raises(ValidationError):
        ScoreItem(index=0, score=-1, reason="r", topic="AI")


def test_헤드라인이_30자를_넘으면_거부한다():
    """카톡 200자 제약에서 파생된 규칙. 모델이 직접 강제한다."""
    article = Article(ranked=_ranked(), body="본문", body_source="trafilatura")
    with pytest.raises(ValidationError):
        Summary(
            article=article,
            headline="가" * 31,
            bullets=["요점"],
            why_it_matters="중요한 이유",
        )


def test_헤드라인이_30자면_통과한다():
    article = Article(ranked=_ranked(), body="본문", body_source="trafilatura")
    summary = Summary(
        article=article,
        headline="가" * 30,
        bullets=["요점"],
        why_it_matters="중요한 이유",
    )
    assert len(summary.headline) == 30


def _ranked() -> RankedItem:
    return RankedItem(item=_raw(), score=82, reason="관심사 정중앙", topic="backend")


def test_body_source는_정해진_값만_받는다():
    with pytest.raises(ValidationError):
        Article(ranked=_ranked(), body="본문", body_source="아무거나")


def test_번들이_중첩_JSON_왕복을_견딘다():
    """파일로 쓰고 읽는 경로 전체를 확인한다."""
    bundle = RawBundle(
        window_start="2026-11-09T22:20:00+00:00",
        window_end="2026-11-10T22:20:00+00:00",
        items=[_raw()],
        source_counts={"토스_기술블로그": 1},
        errors=[],
    )
    restored = RawBundle.model_validate(bundle.model_dump())
    assert restored == bundle
    assert restored.items[0].title == "결제 서버 P99 40ms 달성기"


def test_SourceError는_실패_성격을_요구한다():
    """kind가 없으면 404와 503이 같은 기록이 된다."""
    with pytest.raises(ValidationError):
        SourceError(source="s", message="m")


def test_SourceError의_kind는_정해진_값만_받는다():
    with pytest.raises(ValidationError):
        SourceError(source="s", kind="아무거나", message="m")


def test_폴백_이유는_없어도_된다():
    article = Article(ranked=_ranked(), body="본문", body_source="trafilatura")
    assert article.fallback_reason is None


def test_폴백_이유를_담을_수_있다():
    article = Article(
        ranked=_ranked(), body="발췌", body_source="rss_excerpt",
        fallback_reason="HTTP 403 — 봇 차단",
    )
    assert article.fallback_reason == "HTTP 403 — 봇 차단"


def test_에러가_담긴_번들도_왕복한다():
    bundle = RawBundle(
        window_start="2026-11-09T22:20:00+00:00",
        window_end="2026-11-10T22:20:00+00:00",
        items=[],
        source_counts={"깨진소스": 0},
        errors=[SourceError(source="깨진소스", kind="config", message="HTTP 404")],
    )
    restored = RawBundle.model_validate(bundle.model_dump())
    assert restored.errors[0].kind == "config"


def test_ScoreSheet가_LLM_출력_모양을_담는다():
    sheet = ScoreSheet(scores=[ScoreItem(index=0, score=80, reason="r", topic="AI")])
    assert sheet.scores[0].index == 0


def test_빈_브리핑도_유효하다():
    """임계값 통과분이 0건인 날이 정상 상태다."""
    briefing = Briefing(
        window_start="2026-11-09T22:20:00+00:00",
        window_end="2026-11-10T22:20:00+00:00",
        summaries=[],
        considered=10,
    )
    assert briefing.summaries == []


def test_최고_점수는_없어도_된다():
    """수집이 0건이면 최고 점수가 존재하지 않는다."""
    bundle = RankedBundle(
        window_start="2026-11-09T22:20:00+00:00",
        window_end="2026-11-10T22:20:00+00:00",
        selected=[], all_scores=[],
    )
    assert bundle.max_score is None


def test_RankedBundle과_ArticlesBundle이_왕복한다():
    ranked = RankedBundle(
        window_start="2026-11-09T22:20:00+00:00",
        window_end="2026-11-10T22:20:00+00:00",
        selected=[_ranked()],
        all_scores=[ScoreItem(index=0, score=82, reason="관심사 정중앙", topic="backend")],
    )
    assert RankedBundle.model_validate(ranked.model_dump()) == ranked

    articles = ArticlesBundle(
        window_start="2026-11-09T22:20:00+00:00",
        window_end="2026-11-10T22:20:00+00:00",
        articles=[Article(ranked=_ranked(), body="본문", body_source="rss_excerpt")],
    )
    assert ArticlesBundle.model_validate(articles.model_dump()) == articles
