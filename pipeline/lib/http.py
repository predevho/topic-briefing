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
