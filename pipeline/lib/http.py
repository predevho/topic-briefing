"""HTTP 수집과 상태 코드 분류.

수집(collect)·본문 확보(enrich)·LLM 예외 분류(llm)가 모두 이 모듈을 거친다.
계획 3의 카카오톡·슬랙 전송도 같은 규칙을 쓴다.
분류 규칙이 한곳에만 있어야 "403을 어디선 재시도하고 어디선 안 하는" 일이
생기지 않는다.
"""

from dataclasses import dataclass
from typing import Callable

import httpx

from pipeline.lib.retry import Permanent, Transient

DEFAULT_TIMEOUT = 20.0
USER_AGENT = "briefing-bot/0.1"

# 기다리면 되는 4xx. 429는 레이트 리밋, 408은 요청 타임아웃,
# 425는 "너무 이르다(Too Early)".
TRANSIENT_CLIENT_STATUSES = frozenset({408, 425, 429})

# 5xx 중에서도 이 둘은 영구적이다 — 서버가 그 기능을 지원하지 않는다.
PERMANENT_SERVER_STATUSES = frozenset({501, 505})

# 영구 이전. 자동으로 따라가되 설정을 고치라고 알려야 한다.
# 302/303/307은 임시 이전이므로 기록하지 않는다.
PERMANENT_REDIRECTS = frozenset({301, 308})


@dataclass(frozen=True)
class FetchResult:
    content: bytes
    final_url: str
    # 301/308을 거쳤으면 원래 주소. sources.yaml 갱신 신호다.
    moved_from: str | None = None


def parse_retry_after(value: str | None) -> float | None:
    """Retry-After 헤더를 초로 바꾼다.

    초 단위 숫자만 지원한다. HTTP-date 형식("Wed, 21 Oct ...")은 드물고,
    None을 돌려주면 호출자가 지수 백오프로 대체하므로 문제가 없다.
    """
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return max(0.0, seconds)


def classify_status(
    status: int,
    *,
    url: str,
    retry_after: float | None = None,
    detail: str = "",
) -> None:
    """2xx가 아니면 Transient 또는 Permanent로 분류해 던진다."""
    if 200 <= status < 300:
        return

    # 메시지에 URL을 넣는다. 로그만 보고 어느 소스인지 알아야 한다.
    suffix = f" — {detail}" if detail else ""
    message = f"{url} HTTP {status}{suffix}"

    if status in TRANSIENT_CLIENT_STATUSES:
        raise Transient(message, retry_after=retry_after)
    if status in PERMANENT_SERVER_STATUSES:
        raise Permanent(message)
    if 500 <= status < 600:
        raise Transient(message, retry_after=retry_after)

    # 나머지 4xx(400/401/403/404/410/451 등)는 전부 영구적이다.
    # 403은 봇 차단이라 재시도해도 같고, 404는 주소를 고쳐야 한다.
    raise Permanent(message)


GetFn = Callable[..., httpx.Response]


def _httpx_get(url: str, timeout: float, user_agent: str) -> httpx.Response:
    return httpx.get(
        url,
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": user_agent},
    )


def fetch(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    user_agent: str = USER_AGENT,
    get: GetFn | None = None,
) -> FetchResult:
    """URL을 가져온다. 실패는 Transient/Permanent로 분류해 던진다."""
    getter = get or _httpx_get

    try:
        response = getter(url, timeout, user_agent)
    # --- 가장 구체적인 영구 실패부터 ---
    # httpx.InvalidURL은 httpx.HTTPError의 하위가 아니다. 따로 잡지 않으면
    # 주소 오타가 분류되지 않은 예외로 새어 나간다.
    except httpx.InvalidURL as error:
        raise Permanent(f"{url} 주소 형식 오류: {error}") from error
    except httpx.UnsupportedProtocol as error:
        raise Permanent(f"{url} 지원하지 않는 스킴: {error}") from error
    except httpx.TooManyRedirects as error:
        raise Permanent(f"{url} 리다이렉트 루프: {error}") from error
    # --- 일시적 전송 실패 ---
    except httpx.TimeoutException as error:
        raise Transient(f"{url} 시간 초과: {error}") from error
    except httpx.RequestError as error:
        # NetworkError(ConnectError/ReadError), ProtocolError 등.
        raise Transient(f"{url} 전송 실패: {type(error).__name__}: {error}") from error

    # 301/308을 거쳤으면 원래 주소를 기록한다.
    moved_from: str | None = None
    for hop in response.history:
        if hop.status_code in PERMANENT_REDIRECTS:
            moved_from = str(hop.url)
            break

    classify_status(
        response.status_code,
        url=url,
        retry_after=parse_retry_after(response.headers.get("retry-after")),
    )

    return FetchResult(
        content=response.content,
        final_url=str(response.url),
        moved_from=moved_from,
    )


# --- 폼 POST ---
#
# fetch는 GET 전용이다(_httpx_get). 카카오 토큰 교환·카카오 발송은 폼
# POST라서 전송 계층이 따로 필요하다. **분류 규칙은 위의 classify_status를
# 그대로 쓴다** — 이 모듈 머리말이 말하는 "한곳"이 여기다.

# 폼 POST의 Content-Type. 카카오는 토큰·발송 둘 다 이것만 받는다
# (본문 전체를 JSON으로 보내면 거부한다).
FORM = "application/x-www-form-urlencoded;charset=utf-8"

PostFn = Callable[..., httpx.Response]


def _classified(call: Callable[[], httpx.Response], *, label: str) -> httpx.Response:
    """요청을 보내고 실패를 분류해 던진다. 2xx면 응답을 돌려준다.

    `label`은 **메시지에 쓰는 이름**이다. 보통은 URL이지만, 슬랙 웹훅처럼
    URL 자체가 비밀인 경우 "Slack webhook" 같은 이름을 넘긴다 — 실패 메시지는
    runs.errors와 Actions 로그에 남고, 리포가 퍼블릭이라 로그도 공개다.
    """
    try:
        response = call()
    except httpx.TimeoutException as error:
        raise Transient(f"{label} 시간 초과: {error}") from error
    except httpx.RequestError as error:
        raise Transient(
            f"{label} 전송 실패: {type(error).__name__}: {error}"
        ) from error

    # **스스로 던진다.** `raise classify_status(...)`가 아니다 — 반환값이
    # None이라 2xx에서 `raise None`이 되어 TypeError로 바뀐다.
    #
    # 본문을 detail에 싣되 자른다. 카카오·슬랙 에러 본문은 짧지만
    # (`no_service`), 프록시가 HTML 페이지를 돌려주면 로그가 그것으로 덮인다.
    classify_status(response.status_code, url=label, detail=response.text[:200])
    return response


def _httpx_post(
    url: str, data: dict[str, str], headers: dict[str, str], timeout: float
) -> httpx.Response:
    return httpx.post(url, data=data, headers=headers, timeout=timeout)


def post_form(
    url: str,
    *,
    data: dict[str, str],
    headers: dict[str, str],
    timeout: float = DEFAULT_TIMEOUT,
    send: PostFn = _httpx_post,
) -> dict:
    """폼을 POST하고 JSON을 돌려준다. 실패는 분류해 던진다.

    `send`는 테스트에서 갈아끼우는 자리다. `fetch`의 `get`과 같은 방식이다
    — 실패 경로를 실제 네트워크 없이 확인할 수 있어야 한다.
    """
    response = _classified(lambda: send(url, data, headers, timeout), label=url)

    try:
        return response.json()
    except ValueError as error:
        # 점검 페이지나 프록시가 200에 HTML을 실어 보내는 경우다.
        # 그냥 두면 JSONDecodeError가 분류 없이 새어 나간다.
        raise Permanent(
            f"{url} 응답이 JSON이 아니다 (HTTP {response.status_code}): "
            f"{response.text[:200]}"
        ) from error


# --- JSON POST ---
#
# 슬랙 웹훅용이다. 본문은 JSON이고, 응답은 JSON이 아니라 **텍스트**("ok")다.
# 그래서 post_form과 반환형이 다르다. 전송과 분류는 _classified를 공유한다.

def _httpx_post_json(
    url: str, payload: dict, timeout: float, headers: dict[str, str] | None
) -> httpx.Response:
    return httpx.post(url, json=payload, timeout=timeout, headers=headers)


def post_json(
    url: str,
    *,
    payload: dict,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    label: str | None = None,
    send: PostFn = _httpx_post_json,
) -> str:
    """JSON을 POST하고 응답 본문을 문자열로 돌려준다. 실패는 분류해 던진다.

    `label`을 넘기면 실패 메시지에 URL 대신 그 이름을 쓴다. URL이 비밀일 때
    (슬랙 웹훅) 쓴다. `headers`는 키를 실을 때 쓴다(임베딩 API, 2026-11-23) —
    헤더는 실패 메시지에 들어가지 않는다.
    """
    response = _classified(lambda: send(url, payload, timeout, headers), label=label or url)
    return response.text
