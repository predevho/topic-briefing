"""시각 처리 규칙을 한곳에 모은다.

규칙:
- 저장은 전부 UTC ISO 8601.
- 윈도우 계산도 UTC로 한다.
- KST는 화면 표시에만 쓴다.
"""

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

KST = timezone(timedelta(hours=9))

# 장애 복구 시 수집량·토큰 폭증을 막는 상한.
MAX_WINDOW_HOURS = 96

# 계획 3의 Actions 워크플로가 쓰는 발송 시각과 cron.
# 여기 두는 이유: 이것이 맞는지 테스트로 고정해야 한다. 틀리기 쉬운 이유가
# 두 겹이기 때문이다.
#   1. UTC 22:20 + 9시간은 "익일" 07:20이다 → KST 요일이 하루 앞선다
#   2. cron의 요일은 0 = 일요일인데 datetime.weekday()는 0 = 월요일이다
# 한 칸 밀리면 토요일에 발송되고 월요일이 빠진다 — 월요일은 주말 해외
# 콘텐츠를 72시간 윈도우로 받는 날이라 하필 가장 중요한 날이 사라진다.
SEND_HOUR_UTC = 22
SEND_MINUTE_UTC = 20
SEND_CRON_UTC = "20 22 * * 0-4"   # KST 월~금 07:20


def to_utc_iso(value: str | None) -> str | None:
    """RSS의 발행 시각 문자열을 UTC ISO 8601로 정규화한다.

    파싱 실패 시 예외를 던지지 않고 None을 돌려준다. 한 건의 날짜 오류로
    수집 전체가 중단되는 것을 막기 위함이다. 호출자가 None을 걸러낸다.
    """
    if not value:
        return None

    parsed: datetime | None = None

    # 1) RFC 822 / RFC 2822 — "Tue, 10 Nov 2026 14:30:00 +0900"
    #    국내 매체 RSS에서 가장 흔하다.
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        parsed = None

    # 2) ISO 8601 — "2026-11-10T05:30:00Z" 또는 "+09:00"
    if parsed is None:
        try:
            # fromisoformat은 "Z"를 직접 못 읽으므로 "+00:00"으로 바꿔준다.
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None

    # 타임존 표기가 없는 naive datetime은 UTC로 간주한다.
    # 추측해서 KST로 보정하면 9시간 틀리는 버그가 조용히 생긴다.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc).isoformat()


def _require_aware(moment: datetime, label: str) -> None:
    if moment.tzinfo is None:
        raise ValueError(f"{label}에 타임존이 없다. UTC를 명시해야 한다: {moment!r}")


def compute_window(
    *,
    now: datetime,
    last_sent_at: datetime | None,
) -> tuple[datetime, datetime]:
    """수집 윈도우 (시작, 끝)을 돌려준다.

    "마지막 발송 이후"라는 규칙 하나로 평일·주말·공휴일·장애 복구를 모두
    처리한다. 요일 분기가 없다.
    """
    _require_aware(now, "now")
    if last_sent_at is not None:
        _require_aware(last_sent_at, "last_sent_at")

    floor = now - timedelta(hours=MAX_WINDOW_HOURS)

    if last_sent_at is None:
        start = floor
    else:
        # max()로 상한을 적용한다. 오래 멈췄어도 96시간 전까지만 본다.
        start = max(last_sent_at, floor)

    return start, now
