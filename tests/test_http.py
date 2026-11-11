import httpx
import pytest

from pipeline.lib.http import (
    FetchResult,
    classify_status,
    fetch,
    parse_retry_after,
)
from pipeline.lib.retry import Permanent, Transient

URL = "https://example.com/rss"


def _response(status: int, **kwargs) -> httpx.Response:
    """테스트용 응답. httpx.Response를 직접 만들 수 있다."""
    kwargs.setdefault("request", httpx.Request("GET", URL))
    return httpx.Response(status, **kwargs)


# --- Retry-After 파싱 ---

def test_초_단위_숫자를_읽는다():
    assert parse_retry_after("7") == 7.0


def test_공백이_섞여도_읽는다():
    assert parse_retry_after("  7  ") == 7.0


def test_없으면_None이다():
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None


def test_HTTP_날짜_형식은_None으로_둔다():
    """드문 형식이다. 지수 백오프로 대체된다."""
    assert parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT") is None


def test_음수는_0으로_만든다():
    assert parse_retry_after("-5") == 0.0


# --- 상태 코드 분류 ---

def test_2xx는_통과한다():
    assert classify_status(200, url=URL) is None
    assert classify_status(204, url=URL) is None


def test_429는_일시적이고_retry_after를_전달한다():
    with pytest.raises(Transient) as caught:
        classify_status(429, url=URL, retry_after=7.0)
    assert caught.value.retry_after == 7.0


def test_408과_5xx는_일시적이다():
    for status in (408, 425, 500, 502, 503, 504):
        with pytest.raises(Transient):
            classify_status(status, url=URL)


def test_501과_505는_영구적이다():
    """서버가 지원하지 않는 것이다. 기다려도 생기지 않는다."""
    for status in (501, 505):
        with pytest.raises(Permanent):
            classify_status(status, url=URL)


def test_403은_영구적이다():
    """봇 차단. 100번 해도 같다. 이 구분이 enrich에서 중요하다."""
    with pytest.raises(Permanent, match="403"):
        classify_status(403, url=URL)


def test_401_404_410도_영구적이다():
    for status in (400, 401, 404, 410, 451):
        with pytest.raises(Permanent):
            classify_status(status, url=URL)


def test_에러_메시지에_URL이_들어간다():
    """로그만 보고 어느 소스인지 알아야 한다."""
    with pytest.raises(Permanent, match="example.com"):
        classify_status(404, url=URL)


def test_상세_설명을_덧붙일_수_있다():
    """Claude API는 본문에 원인을 담는다. 계획 3의 슬랙도 마찬가지로
    channel_not_found 같은 이유를 본문에 담는다."""
    with pytest.raises(Permanent, match="channel_not_found"):
        classify_status(404, url=URL, detail="channel_not_found")


# --- 수집 ---

def test_성공하면_본문과_최종_주소를_돌려준다():
    result = fetch(URL, get=lambda *a, **k: _response(200, content=b"<rss/>"))

    assert isinstance(result, FetchResult)
    assert result.content == b"<rss/>"
    assert result.final_url == URL
    assert result.moved_from is None


def test_영구_리다이렉트를_거치면_원래_주소를_기록한다():
    """자동으로 따라가지만 sources.yaml을 고치라고 알려줘야 한다."""
    old = httpx.Request("GET", "https://old.example.com/rss")
    hop = httpx.Response(301, request=old,
                         headers={"location": URL})
    final = _response(200, content=b"<rss/>", history=[hop])

    result = fetch(URL, get=lambda *a, **k: final)

    assert result.moved_from == "https://old.example.com/rss"


def test_일시_리다이렉트는_기록하지_않는다():
    """302는 임시 이전이다. 설정을 고칠 일이 아니다."""
    old = httpx.Request("GET", "https://old.example.com/rss")
    hop = httpx.Response(302, request=old, headers={"location": URL})
    final = _response(200, content=b"<rss/>", history=[hop])

    assert fetch(URL, get=lambda *a, **k: final).moved_from is None


def test_429의_Retry_After를_예외에_담는다():
    def get(*a, **k):
        return _response(429, headers={"Retry-After": "12"})

    with pytest.raises(Transient) as caught:
        fetch(URL, get=get)
    assert caught.value.retry_after == 12.0


def test_타임아웃은_일시적이다():
    def get(*a, **k):
        raise httpx.ReadTimeout("시간 초과")

    with pytest.raises(Transient, match="시간|Timeout|timeout"):
        fetch(URL, get=get)


def test_연결_실패는_일시적이다():
    def get(*a, **k):
        raise httpx.ConnectError("연결 거부")

    with pytest.raises(Transient):
        fetch(URL, get=get)


def test_지원하지_않는_스킴은_영구적이다():
    """sources.yaml에 주소를 잘못 적은 경우다."""
    def get(*a, **k):
        raise httpx.UnsupportedProtocol("스킴 오류")

    with pytest.raises(Permanent):
        fetch(URL, get=get)


def test_리다이렉트_루프는_영구적이다():
    def get(*a, **k):
        raise httpx.TooManyRedirects("루프")

    with pytest.raises(Permanent):
        fetch(URL, get=get)


def test_InvalidURL도_영구적이다():
    """함정: httpx.InvalidURL은 httpx.HTTPError의 하위가 아니다.
    except httpx.HTTPError로는 잡히지 않으므로 따로 잡아야 한다."""
    assert not issubclass(httpx.InvalidURL, httpx.HTTPError)

    def get(*a, **k):
        raise httpx.InvalidURL("주소 형식 오류")

    with pytest.raises(Permanent):
        fetch(URL, get=get)
