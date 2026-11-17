"""카카오 토큰 갱신.

최초 인증(인가 코드 → refresh_token)은 `scripts/kakao_auth.py`가 한다.
사람이 브라우저에서 동의해야 하므로 파이프라인에 둘 수 없다.

여기는 **매일 쓰는 쪽**이다 — refresh_token으로 access_token을 받는다.

access_token은 6시간(21,599초)이고 refresh_token은 **60일**이다
(2026-11-17 실측: `refresh_token_expires_in: 5184000`). 매일 도는
파이프라인에서는 access_token을 매번 새로 받고 refresh_token은 그대로
쓴다 — 회전될 때만 저장한다(`should_store` 참조).

HTTP는 `lib/http.py`의 `post_form`에 맡긴다. 전송과 실패 분류가 거기
한곳에 있어야 "403을 어디선 재시도하고 어디선 안 하는" 일이 생기지 않는다.
이 파일은 **카카오 규약**만 안다 — 폼 필드 이름, 토큰 회전 규칙.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from pipeline.lib.http import DEFAULT_TIMEOUT, FORM, post_form
from pipeline.lib.retry import Permanent

TOKEN_URL = "https://kauth.kakao.com/oauth/token"


@dataclass(frozen=True)
class KakaoTokens:
    access_token: str
    # 기존 만료가 1개월 미만일 때만 온다. **안 오는 것이 정상이다.**
    refresh_token: str | None = None
    refresh_token_expires_in: int | None = None


def access_token(
    *,
    refresh_token: str,
    client_id: str,
    client_secret: str,
    post: Callable[..., dict] = post_form,
) -> KakaoTokens:
    """refresh_token으로 access_token을 받는다."""
    payload = post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        headers={"Content-Type": FORM},
        timeout=DEFAULT_TIMEOUT,
    )

    # 카카오는 HTTP 200으로 `{"error": "invalid_grant"}`를 돌려줄 수 있다.
    # 상태 코드만 보면 성공으로 읽힌다.
    if "access_token" not in payload:
        raise Permanent(f"카카오 응답에 access_token이 없다: {sorted(payload)}")

    return KakaoTokens(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),
        refresh_token_expires_in=payload.get("refresh_token_expires_in"),
    )


def should_store(tokens: KakaoTokens) -> bool:
    """회전된 refresh_token이 왔을 때만 저장한다.

    카카오는 기존 만료가 1개월 미만일 때만 새 것을 준다. 매일 저장하면
    한 달에 29번은 같은 값을 다시 쓰는 셈이다.
    """
    return tokens.refresh_token is not None


def rotated_expiry(tokens: KakaoTokens, *, now: datetime) -> datetime:
    """회전된 refresh_token의 만료 **시각**. kakao_auth.refresh_token_expires_at에 쓴다.

    카카오는 남은 **초**(refresh_token_expires_in)를 주고 테이블은 **시각**을
    담는다. 변환을 여기 한 곳에서만 한다 — 두 곳에서 하다가 발송 확인
    스크립트가 없는 컬럼(refresh_token_expires_in)에 쓰는 버그가 났다(2026-11-17).

    카카오는 새 refresh_token과 수명을 함께 준다. 수명만 빠졌으면 **모르는 값을
    60일로 지어내지 않고** now를 돌려준다. 그러면 토큰 가드가 바로 "0일 남음"을
    알려 사람이 재인증한다 — 안전한 쪽으로 틀린다. 토큰 자체는 저장해야 한다.
    """
    if tokens.refresh_token_expires_in is None:
        return now
    return now + timedelta(seconds=tokens.refresh_token_expires_in)
