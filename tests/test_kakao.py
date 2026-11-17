"""카카오 토큰 갱신 테스트.

실제 카카오 서버를 부르지 않는다. 두 층을 따로 본다.

  - `access_token` — `post`를 주입해 **응답 해석**만 본다
  - `post_form`    — `send`를 주입해 **HTTP 실패 분류**를 본다

층을 나눈 이유: 토큰 갱신은 매일 07:00에 사람 없이 돈다. 여기서 분류되지
않은 예외가 새면 "왜 안 왔지"로 아침을 시작한다. 실패 경로가 실은 성공
경로보다 중요하다.
"""

import httpx
import pytest

from pipeline.lib.kakao import (
    TOKEN_URL,
    KakaoTokens,
    access_token,
    post_form,
    should_store,
)
from pipeline.lib.retry import Permanent, Transient


def _response(status: int, **kwargs) -> httpx.Response:
    """테스트용 응답. tests/test_http.py와 같은 방식이다."""
    kwargs.setdefault("request", httpx.Request("POST", TOKEN_URL))
    return httpx.Response(status, **kwargs)


def _call(send) -> dict:
    """post_form을 주입한 send로 부른다. 인자가 매번 같아서 묶었다."""
    return post_form(TOKEN_URL, data={}, headers={}, timeout=1.0, send=send)


# --- 응답 해석 ---

def test_refresh_token으로_access_token을_받는다():
    def fake_post(url, data, headers, timeout):
        assert data["grant_type"] == "refresh_token"
        return {"access_token": "AT", "expires_in": 21599}

    tokens = access_token(
        refresh_token="RT", client_id="ID", client_secret="SECRET", post=fake_post
    )

    assert tokens.access_token == "AT"
    assert tokens.refresh_token is None      # 회전되지 않았다


def test_새_refresh_token이_오면_담아_준다():
    """카카오는 기존 만료가 1개월 미만일 때만 새 것을 준다.
    왔는데 저장하지 않으면 다음 달에 로그인이 끊긴다.
    """
    def fake_post(url, data, headers, timeout):
        return {
            "access_token": "AT",
            "expires_in": 21599,
            "refresh_token": "NEW_RT",
            "refresh_token_expires_in": 5184000,
        }

    tokens = access_token(
        refresh_token="RT", client_id="ID", client_secret="SECRET", post=fake_post
    )

    assert tokens.refresh_token == "NEW_RT"
    assert tokens.refresh_token_expires_in == 5184000


def test_access_token이_없으면_영구_실패다():
    """카카오가 HTTP 200으로 에러 본문을 돌려주는 경우가 있다
    (`{"error": "invalid_grant"}`). 상태 코드만 보면 성공으로 읽힌다.

    키나 앱 설정을 고쳐야 하므로 재시도 대상이 아니다.
    """
    def fake_post(url, data, headers, timeout):
        return {"error": "invalid_grant", "error_description": "refresh token expired"}

    with pytest.raises(Permanent, match="access_token"):
        access_token(
            refresh_token="RT", client_id="ID", client_secret="S", post=fake_post
        )


def test_회전된_토큰만_저장한다():
    """매일 저장하면 쓸데없이 쓰기가 생긴다. 한 달에 한 번이면 된다."""
    assert should_store(KakaoTokens(access_token="AT", refresh_token="NEW")) is True
    assert should_store(KakaoTokens(access_token="AT")) is False


# --- HTTP 실패 분류 ---
#
# 분류를 틀리면 두 방향으로 손해다. 영구 실패를 재시도하면 시간만 쓰고,
# 일시적 실패를 포기하면 그날 브리핑이 안 간다.

def test_인증_실패는_영구다():
    """401은 키 오타나 앱 설정 변경이다. 재시도해도 같다."""
    with pytest.raises(Permanent, match="HTTP 401"):
        _call(lambda *a, **k: _response(401, text="invalid client"))


def test_서버_오류는_일시적이다():
    with pytest.raises(Transient, match="HTTP 500"):
        _call(lambda *a, **k: _response(500))


def test_시간_초과는_일시적이다():
    """http.fetch와 같은 처리다. 잡지 않으면 분류되지 않은 예외로 샌다."""
    def slow(*a, **k):
        raise httpx.TimeoutException("too slow")

    with pytest.raises(Transient, match="시간 초과"):
        _call(slow)


def test_JSON이_아닌_응답은_영구다():
    """프록시나 점검 페이지가 200에 HTML을 실어 보내는 경우다.
    그냥 .json()을 부르면 JSONDecodeError가 분류 없이 새어 나간다.
    """
    with pytest.raises(Permanent, match="JSON"):
        _call(lambda *a, **k: _response(200, text="<html>under maintenance</html>"))
