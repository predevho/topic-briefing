"""카카오 토큰 갱신.

최초 인증(인가 코드 → refresh_token)은 `scripts/kakao_auth.py`가 한다.
사람이 브라우저에서 동의해야 하므로 파이프라인에 둘 수 없다.

여기는 **매일 쓰는 쪽**이다 — refresh_token으로 access_token을 받는다.

access_token은 6시간(21,599초)이고 refresh_token은 **60일**이다
(2026-11-17 실측: `refresh_token_expires_in: 5184000`). 매일 도는
파이프라인에서는 access_token을 매번 새로 받고 refresh_token은 그대로
쓴다 — 회전될 때만 저장한다(`should_store` 참조).

`lib/http.py`의 `fetch`를 쓰지 않는 이유: 그쪽은 GET 전용이다(`_httpx_get`).
토큰 교환은 폼 POST라서 전송 계층을 따로 둔다. 다만 **실패 분류 규칙은
공유한다** — `classify_status`를 그대로 부른다. 규칙이 두 곳에 있으면
한쪽만 고치는 날이 온다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import httpx

from pipeline.lib.http import classify_status
from pipeline.lib.retry import Permanent, Transient

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
FORM = "application/x-www-form-urlencoded;charset=utf-8"

# 토큰 교환은 한 번에 끝나야 한다. fetch의 20초와 같게 둔다.
TOKEN_TIMEOUT = 20.0

PostFn = Callable[..., httpx.Response]


@dataclass(frozen=True)
class KakaoTokens:
    access_token: str
    # 기존 만료가 1개월 미만일 때만 온다. **안 오는 것이 정상이다.**
    refresh_token: str | None = None
    refresh_token_expires_in: int | None = None


def _httpx_post(
    url: str, data: dict[str, str], headers: dict[str, str], timeout: float
) -> httpx.Response:
    return httpx.post(url, data=data, headers=headers, timeout=timeout)


def post_form(
    url: str,
    *,
    data: dict[str, str],
    headers: dict[str, str],
    timeout: float = TOKEN_TIMEOUT,
    send: PostFn = _httpx_post,
) -> dict:
    """폼을 POST하고 JSON을 돌려준다. 실패는 분류해 던진다.

    `send`는 테스트에서 갈아끼우는 자리다. `http.fetch`의 `get`과 같은
    방식이다 — 실패 경로를 실제 네트워크 없이 확인할 수 있어야 한다.
    """
    try:
        response = send(url, data, headers, timeout)
    except httpx.TimeoutException as error:
        raise Transient(f"{url} 시간 초과: {error}") from error
    except httpx.RequestError as error:
        raise Transient(
            f"{url} 전송 실패: {type(error).__name__}: {error}"
        ) from error

    # **스스로 던진다.** `raise classify_status(...)`가 아니다 — 반환값이
    # None이라 2xx에서 `raise None`이 되어 TypeError로 바뀐다.
    #
    # 본문을 detail에 싣되 자른다. 카카오 에러 본문은 짧지만, 프록시가
    # HTML 페이지를 돌려주면 로그가 그것으로 덮인다.
    classify_status(
        response.status_code,
        url=url,
        detail=response.text[:200],
    )

    try:
        return response.json()
    except ValueError as error:
        # 점검 페이지나 프록시가 200에 HTML을 실어 보내는 경우다.
        # 그냥 두면 JSONDecodeError가 분류 없이 새어 나간다.
        raise Permanent(
            f"{url} 응답이 JSON이 아니다 (HTTP {response.status_code}): "
            f"{response.text[:200]}"
        ) from error


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
        timeout=TOKEN_TIMEOUT,
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
