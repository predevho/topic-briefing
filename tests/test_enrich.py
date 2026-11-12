from pathlib import Path

import pytest

from pipeline.enrich import (
    ARTICLE_ATTEMPTS,
    BODY_MAX_CHARS,
    BODY_MIN_CHARS,
    REQUEST_DELAY,
    enrich,
    extract_body,
)
from pipeline.lib.http import FetchResult
from pipeline.lib.retry import Permanent, Transient
from pipeline.models import RankedBundle, RankedItem, RawItem

FIXTURES = Path(__file__).parent / "fixtures"
WINDOW = ("2026-11-09T22:20:00+00:00", "2026-11-10T22:20:00+00:00")


def _ranked(index: int = 0, excerpt: str = "RSS 발췌 내용") -> RankedItem:
    return RankedItem(
        item=RawItem(
            source="토스_기술블로그",
            title=f"제목 {index}",
            url=f"https://toss.tech/a/{index}",
            published="2026-11-10T05:30:00+00:00",
            excerpt=excerpt,
        ),
        score=85,
        reason="이유",
        topic="backend",
    )


def _bundle(items) -> RankedBundle:
    return RankedBundle(
        window_start=WINDOW[0], window_end=WINDOW[1],
        selected=items, all_scores=[],
    )


def _ok_fetch():
    data = (FIXTURES / "article.html").read_bytes()

    def fetch(url: str) -> FetchResult:
        return FetchResult(content=data, final_url=url, moved_from=None)

    return fetch


def _html(body_text: str) -> bytes:
    return f"<html><body><article><p>{body_text}</p></article></body></html>".encode()


def _enrich(items, fetch=None, sleeps=None):
    recorded: list[float] = [] if sleeps is None else sleeps
    bundle = enrich(
        ranked=_bundle(items),
        fetch=fetch or _ok_fetch(),
        sleep=recorded.append,
    )
    return bundle, recorded


# --- 본문 추출 ---

def test_본문을_추출한다():
    body = extract_body((FIXTURES / "article.html").read_bytes())

    assert body is not None
    assert "커넥션 풀 고갈이 병목" in body


def test_내비게이션과_광고와_푸터를_걸러낸다():
    body = extract_body((FIXTURES / "article.html").read_bytes())

    assert "채용" not in body
    assert "10만원 할인" not in body
    assert "모든 권리 보유" not in body


def test_내비게이션만_있는_HTML은_None을_돌려준다():
    """**trafilatura는 이걸 None으로 주지 않는다.** 2026-11-12 확인:
    `<nav>menu</nav>`를 넣으면 `'menu'`를 돌려준다. 그대로 본문으로 쓰면
    브리핑에 "메뉴"가 실린다. 길이 하한이 필요한 이유다.
    """
    assert extract_body(b"<html><body><nav>\xeb\xa9\x94\xeb\x89\xb4</nav></body></html>") is None


def test_너무_짧은_추출은_본문으로_보지_않는다():
    """RSS 발췌가 보통 250자다. 그보다 짧은 추출은 발췌가 낫다."""
    assert extract_body(_html("짧다")) is None


def test_하한을_넘으면_본문으로_본다():
    body = extract_body(_html("가" * BODY_MIN_CHARS))
    assert body is not None


def test_HTML이_아니면_None을_돌려준다():
    assert extract_body(b"\x00\x01\x02") is None


def test_하한이_발췌_길이보다_작지_않다():
    """하한이 너무 크면 멀쩡한 짧은 글이 발췌로 떨어진다.
    2026-11-12 실측 발췌 중앙값 250자를 기준으로 둔다.
    """
    assert 100 <= BODY_MIN_CHARS <= 400


# --- 정상 경로 ---

def test_본문을_확보하고_출처를_기록한다():
    bundle, _ = _enrich([_ranked()])

    assert len(bundle.articles) == 1
    assert bundle.articles[0].body_source == "trafilatura"
    assert bundle.articles[0].fallback_reason is None
    assert "트랜잭션" in bundle.articles[0].body


def test_본문을_상한에서_자른다():
    bundle, _ = _enrich(
        [_ranked()],
        fetch=lambda url: FetchResult(content=_html("가" * 20000),
                                      final_url=url, moved_from=None),
    )

    assert len(bundle.articles[0].body) <= BODY_MAX_CHARS


def test_상한이_하한보다_크다():
    assert BODY_MAX_CHARS > BODY_MIN_CHARS


def test_요청_사이에_간격을_둔다():
    """상대 서버에 부담을 주지 않는다."""
    _, sleeps = _enrich([_ranked(0), _ranked(1), _ranked(2)])

    # 3건이면 2번 쉰다 (마지막 뒤에는 쉬지 않는다)
    assert len(sleeps) == 2
    assert all(delay >= 1.0 for delay in sleeps)


def test_한_건이면_쉬지_않는다():
    _, sleeps = _enrich([_ranked()])
    assert sleeps == []


def test_선별_결과가_비면_요청하지_않는다():
    calls = []

    def fetch(url: str) -> FetchResult:
        calls.append(url)
        return FetchResult(content=b"", final_url=url, moved_from=None)

    bundle, _ = _enrich([], fetch=fetch)

    assert bundle.articles == []
    assert calls == []


def test_윈도우_경계를_이어받는다():
    bundle, _ = _enrich([_ranked()])
    assert bundle.window_start == WINDOW[0]
    assert bundle.window_end == WINDOW[1]


def test_선별_정보를_그대로_들고_간다():
    """점수·이유·주제는 요약과 화면이 쓴다."""
    bundle, _ = _enrich([_ranked()])
    ranked = bundle.articles[0].ranked

    assert ranked.score == 85
    assert ranked.reason == "이유"
    assert ranked.topic == "backend"


# --- 폴백과 분류 ---

def test_본문_추출_실패시_RSS_발췌로_폴백한다():
    """핵심 요구사항. 한 건 실패로 파이프라인이 죽지 않는다."""
    bundle, _ = _enrich(
        [_ranked(excerpt="발췌로 대체된다")],
        fetch=lambda url: FetchResult(
            content=b"<html><body><nav>menu</nav></body></html>",
            final_url=url, moved_from=None,
        ),
    )

    assert bundle.articles[0].body == "발췌로 대체된다"
    assert bundle.articles[0].body_source == "rss_excerpt"
    assert "추출 실패" in bundle.articles[0].fallback_reason


def test_영구_실패는_재시도하지_않고_즉시_폴백한다():
    """403 봇 차단에 재시도를 걸면 10건이면 수십 초를 버린다.

    2026-11-12 실측: 상위 10건 중 Netflix(Medium)가 403이었다.
    """
    calls = []

    def fetch(url: str) -> FetchResult:
        calls.append(url)
        raise Permanent(f"{url} HTTP 403")

    bundle, sleeps = _enrich([_ranked(excerpt="발췌")], fetch=fetch)

    assert len(calls) == 1                      # 재시도하지 않았다
    assert sleeps == []                          # 백오프도 없었다
    assert bundle.articles[0].body_source == "rss_excerpt"
    assert "403" in bundle.articles[0].fallback_reason


def test_일시_실패는_재시도한_뒤_폴백한다():
    calls = []

    def fetch(url: str) -> FetchResult:
        calls.append(url)
        raise Transient(f"{url} HTTP 503")

    bundle, _ = _enrich([_ranked(excerpt="발췌")], fetch=fetch)

    assert len(calls) == ARTICLE_ATTEMPTS
    assert bundle.articles[0].body_source == "rss_excerpt"
    assert "503" in bundle.articles[0].fallback_reason


def test_재시도_중_성공하면_본문을_쓴다():
    calls = []
    data = (FIXTURES / "article.html").read_bytes()

    def fetch(url: str) -> FetchResult:
        calls.append(url)
        if len(calls) == 1:
            raise Transient("일시 장애")
        return FetchResult(content=data, final_url=url, moved_from=None)

    bundle, _ = _enrich([_ranked()], fetch=fetch)

    assert bundle.articles[0].body_source == "trafilatura"
    assert bundle.articles[0].fallback_reason is None


def test_한_건이_실패해도_나머지는_본문을_쓴다():
    """절대 중단하지 않는다 — spec 8.2."""
    data = (FIXTURES / "article.html").read_bytes()

    def fetch(url: str) -> FetchResult:
        if url.endswith("/0"):
            raise Permanent("HTTP 403")
        return FetchResult(content=data, final_url=url, moved_from=None)

    bundle, _ = _enrich([_ranked(0, excerpt="발췌"), _ranked(1)], fetch=fetch)

    assert len(bundle.articles) == 2
    assert bundle.articles[0].body_source == "rss_excerpt"
    assert bundle.articles[1].body_source == "trafilatura"


def test_본문도_발췌도_없으면_그_건만_제외한다():
    """요약할 재료가 전혀 없으면 보낼 수 없다. 중단은 하지 않는다."""
    def fetch(url: str) -> FetchResult:
        raise Permanent("HTTP 404")

    bundle, _ = _enrich([_ranked(0, excerpt=""), _ranked(1, "발췌 있음")], fetch=fetch)

    assert len(bundle.articles) == 1
    assert bundle.articles[0].body == "발췌 있음"


def test_공백뿐인_발췌도_없는_것으로_본다():
    def fetch(url: str) -> FetchResult:
        raise Permanent("HTTP 404")

    bundle, _ = _enrich([_ranked(0, excerpt="   \n  ")], fetch=fetch)
    assert bundle.articles == []


def test_발췌_폴백도_상한에서_자른다():
    """2026-11-12 실측: Netflix 발췌가 15,633자였다. 전문이 피드에 들어
    있는 소스가 있어서, 폴백 쪽도 자르지 않으면 요약 토큰이 튄다.
    """
    def fetch(url: str) -> FetchResult:
        raise Permanent("HTTP 403")

    bundle, _ = _enrich([_ranked(0, excerpt="가" * 20000)], fetch=fetch)
    assert len(bundle.articles[0].body) <= BODY_MAX_CHARS


def test_분류되지_않은_예외는_삼키지_않는다():
    """fetch 구현의 코드 버그를 발췌 폴백으로 가리면 원인을 못 찾는다."""
    def fetch(url: str) -> FetchResult:
        raise TypeError("코드 버그")

    with pytest.raises(TypeError):
        _enrich([_ranked()], fetch=fetch)


def test_요청_간격이_1초_이상이다():
    assert REQUEST_DELAY >= 1.0
