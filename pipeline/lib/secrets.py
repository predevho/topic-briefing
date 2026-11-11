"""비밀값 접근 단일 통로.

로컬은 .env 파일, GitHub Actions는 Secrets가 환경변수로 주입된다.
호출하는 코드는 그 차이를 모른다.
"""

import os

from dotenv import load_dotenv

# .env가 있으면 환경변수로 올린다. 없으면 조용히 통과한다.
# override=False라 이미 설정된 환경변수를 .env가 덮어쓰지 않는다 —
# Actions에서 Secret이 .env보다 우선해야 한다.
load_dotenv(override=False)


def require(key: str) -> str:
    """환경변수를 읽는다. 없거나 비어 있으면 즉시 RuntimeError."""
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(
            f"환경변수 {key}가 없다. "
            f"로컬이면 .env에, GitHub Actions면 리포지토리 Secrets에 추가한다. "
            f"필요한 키 목록은 .env.example을 본다."
        )
    return value


def optional(key: str, default: str | None = None) -> str | None:
    """없어도 되는 환경변수를 읽는다."""
    value = os.environ.get(key)
    return value if value else default
