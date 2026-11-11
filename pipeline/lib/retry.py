"""재시도 분류.

이 모듈의 요점은 예외를 두 갈래로만 나누는 것이다.

- Transient: 기다리면 된다. 429, 408, 5xx, 타임아웃, 연결 실패.
- Permanent: 설정을 고쳐야 한다. 401, 403, 404, 410, 주소 오타.

상태 코드별로 갈래를 늘리면 호출부마다 분기가 늘어나고, 결국 아무도
그 분기를 유지하지 않는다. "호출자가 뭘 해야 하는가"가 유일한 기준이다.
"""

import time
from typing import Callable, TypeVar

T = TypeVar("T")

DEFAULT_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 1.0

# 한 번에 기다릴 수 있는 최대 시간. 서버가 Retry-After로 몇 시간을
# 요구해도 파이프라인이 그만큼 멈춰 있을 수는 없다.
MAX_DELAY = 30.0


class Transient(RuntimeError):
    """잠시 후 다시 하면 되는 실패.

    retry_after가 있으면(429의 Retry-After 헤더 등) 백오프 대신 그 값을 따른다.
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class Permanent(RuntimeError):
    """설정을 고쳐야 하는 실패. 재시도는 시간과 비용만 쓴다."""


def backoff_delay(attempt: int, *, base_delay: float = DEFAULT_BASE_DELAY) -> float:
    """지수 백오프 간격. attempt는 0부터 센다."""
    return min(MAX_DELAY, base_delay * (2**attempt))


def with_retry(
    call: Callable[[], T],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
    base_delay: float = DEFAULT_BASE_DELAY,
) -> T:
    """Transient만 재시도한다.

    Permanent는 즉시 올린다. 분류되지 않은 예외도 즉시 올린다 —
    코드 버그(TypeError 등)를 재시도로 가리면 원인을 못 찾는다.
    """
    last: Transient | None = None

    for attempt in range(attempts):
        try:
            return call()
        except Permanent:
            # 잡아서 아무것도 하지 않고 그대로 올린다. 아래 except Transient에
            # 걸리지 않게 하려는 것이 아니라(둘은 형제다), 의도를 명시하기 위함이다.
            raise
        except Transient as error:
            last = error
            if attempt == attempts - 1:
                break   # 마지막 시도였다. 쉬지 않고 바로 빠져나간다.
            delay = (
                error.retry_after
                if error.retry_after is not None
                else backoff_delay(attempt, base_delay=base_delay)
            )
            sleep(min(delay, MAX_DELAY))

    assert last is not None   # attempts >= 1이면 반드시 설정된다
    raise last
