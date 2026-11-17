"""카카오 토큰 갱신 테스트.

실제 카카오 서버를 부르지 않는다. `post`를 주입해 **응답 해석**만 본다.
HTTP 실패 분류는 `post_form`의 책임이고 tests/test_http.py에서 본다.

실패 경로가 실은 성공 경로보다 중요하다 — 토큰 갱신은 매일 07:20에
사람 없이 돈다. 여기서 분류되지 않은 예외가 새면 "왜 안 왔지"로
아침을 시작한다.
"""

import pytest

from pipeline.lib.kakao import KakaoTokens, access_token, should_store
from pipeline.lib.retry import Permanent


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


# --- 회전된 토큰의 만료 시각 ---

from datetime import datetime, timedelta, timezone

from pipeline.lib.kakao import rotated_expiry

NOW = datetime(2026, 12, 20, 22, 20, tzinfo=timezone.utc)


def test_회전된_토큰의_만료는_받은_초만큼_뒤다():
    """kakao_auth.refresh_token_expires_at은 **시각**이다. 카카오는 남은
    **초**를 준다. 변환을 한 곳에서만 한다 — 두 곳에서 하다가 Task 6 스크립트가
    없는 컬럼(refresh_token_expires_in)에 쓰는 버그가 났다.
    """
    tokens = KakaoTokens(
        access_token="AT", refresh_token="NEW", refresh_token_expires_in=5184000
    )

    assert rotated_expiry(tokens, now=NOW) == NOW + timedelta(days=60)


def test_수명이_안_왔으면_지금으로_둔다():
    """카카오는 새 refresh_token과 수명을 함께 준다. 수명만 빠지면 **모르는
    값을 60일로 지어내지 않는다.** 지금으로 두면 토큰 가드가 바로 "0일
    남음"으로 알려 사람이 재인증한다 — 안전한 쪽으로 틀린다.

    토큰 자체는 저장해야 한다. 버리면 새로 받은 토큰을 잃는다.
    """
    tokens = KakaoTokens(access_token="AT", refresh_token="NEW")

    assert rotated_expiry(tokens, now=NOW) == NOW
