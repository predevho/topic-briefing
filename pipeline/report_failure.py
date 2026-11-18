"""단계 실패를 슬랙으로 알린다.

GitHub Actions의 실패 메일은 **크래시만 잡는다.** "소스 하나가 석 달째
조용"은 실행이 성공적으로 끝나므로 메일이 오지 않는다 — 그건 lib/guard가
본다. 여기는 진짜로 죽었을 때다.

보고가 답해야 하는 질문은 하나다 — **"지금 손으로 다시 돌려야 하나?"**
수집 윈도우는 `max(마지막 발송, 지금 − 96시간)`이라(lib/timeutil.compute_window),
다음 정기 실행이 놓친 기간을 다 덮는지는 날짜에 따라 다르다.

  - 화요일 하나 실패   → 수요일이 48시간을 덮는다. 그냥 둬도 된다.
  - 금요일 실패        → 다음은 **월요일**이고 공백이 정확히 96시간이다.
                          간신히 덮고, 실행이 늦게 시작하면 그만큼 빠진다.
  - 목·금 연속 실패    → 월요일은 목요일까지만 거슬러 본다. 약 하루치가 영영
                          빠진다. 다시 돌려야 한다.

계획서 원안은 "다음 날이 이틀치를 덮으니 그냥 둬도 된다"는 고정 문구였다.
그래서 마지막 발송 시각을 읽어 **계산한 판단**을 싣는다.

실행: python -m pipeline.report_failure   (워크플로가 실패 시 부른다)
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from typing import Callable

from pipeline.lib.secrets import optional, require
from pipeline.lib.slack import send_warnings
from pipeline.lib.timeutil import KST, MAX_WINDOW_HOURS

# 정기 실행 시각(KST). .github/workflows의 cron `20 22 * * 0-4`(UTC)와 같아야
# 한다 — UTC 일~목 22:20 = KST 월~금 07:20. 바꾸면 둘 다 바꾼다.
RUN_WEEKDAYS = frozenset({0, 1, 2, 3, 4})     # 월~금 (date.weekday())
RUN_HOUR, RUN_MINUTE = 7, 20

# 이보다 여유가 적으면 "간신히"라고 알린다. Actions cron은 흔히 늦게 시작한다.
TIGHT_MARGIN = timedelta(hours=1)

WEEKDAY_KO = "월화수목금토일"


def next_scheduled_run(now: datetime) -> datetime:
    """now 이후의 첫 정기 실행 시각(KST)."""
    local = now.astimezone(KST)
    for offset in range(8):
        day = local.date() + timedelta(days=offset)
        if day.weekday() not in RUN_WEEKDAYS:
            continue
        candidate = datetime(day.year, day.month, day.day, RUN_HOUR, RUN_MINUTE, tzinfo=KST)
        if candidate > local:
            return candidate
    raise AssertionError("일주일 안에 실행일이 없다 — RUN_WEEKDAYS가 비었다")


def _when(moment: datetime) -> str:
    local = moment.astimezone(KST)
    return f"{local:%m/%d}({WEEKDAY_KO[local.weekday()]}) {local:%H:%M}"


def _span(delta: timedelta) -> str:
    minutes = round(delta.total_seconds() / 60)
    if minutes < 60:
        return f"{minutes}분"
    return f"약 {round(minutes / 60)}시간"


def coverage_note(*, last_sent_at: datetime | None, now: datetime) -> str:
    """다음 정기 실행이 놓친 기간을 다 덮는지 말한다."""
    upcoming = next_scheduled_run(now)
    floor = upcoming - timedelta(hours=MAX_WINDOW_HOURS)

    if last_sent_at is None:
        return (f"아직 보낸 적이 없다. 다음 정기 실행({_when(upcoming)})이 "
                f"그 전 {MAX_WINDOW_HOURS}시간을 본다.")

    if last_sent_at < floor:
        lost = floor - last_sent_at
        return (
            f"⚠ 다음 정기 실행({_when(upcoming)})은 {MAX_WINDOW_HOURS}시간까지만 거슬러 본다. "
            f"마지막 발송({_when(last_sent_at)}) 이후 {_span(lost)} 분량이 영영 빠진다. "
            "지금 workflow_dispatch로 다시 돌린다."
        )

    margin = last_sent_at - floor
    if margin < TIGHT_MARGIN:
        return (
            f"다음 정기 실행({_when(upcoming)})이 마지막 발송({_when(last_sent_at)}) 이후를 "
            f"간신히 덮는다 — 여유 {_span(margin)}. 실행이 늦게 시작하면 그만큼 빠진다. "
            "놓치기 싫으면 오늘 workflow_dispatch로 다시 돌린다."
        )

    return (
        f"다음 정기 실행({_when(upcoming)})이 마지막 발송({_when(last_sent_at)}) 이후를 "
        "다 덮는다. 급하지 않으면 그냥 둬도 된다."
    )


def build_report(
    *, failed_step: str, run_url: str, briefing_date: str, coverage: str
) -> list[str]:
    """슬랙에 보낼 줄들. 슬랙의 머리글("브리핑 경고") 아래 글머리표로 붙는다."""
    return [
        f"브리핑 실패 — {briefing_date} · 죽은 단계: {failed_step}",
        f"로그: {run_url}",
        coverage,
    ]


def report(
    *,
    failed_step: str,
    run_url: str,
    now: datetime,
    read_last_sent: Callable[[], datetime | None],
    send: Callable[[list[str]], bool],
) -> bool:
    """실패를 보고한다. 슬랙 전송에 성공하면 True.

    마지막 발송 시각을 못 읽어도 보고는 보낸다 — 실패 원인이 DB일 수 있고,
    그때 보고까지 죽으면 아무것도 모른다.
    """
    try:
        coverage = coverage_note(last_sent_at=read_last_sent(), now=now)
    except Exception as error:  # noqa: BLE001 — 보고가 죽으면 안 된다
        coverage = (
            f"마지막 발송 시각을 못 읽었다({type(error).__name__}: {error}). "
            f"다음 정기 실행은 {_when(next_scheduled_run(now))}이고 "
            f"{MAX_WINDOW_HOURS}시간까지만 거슬러 본다."
        )

    return send(build_report(
        failed_step=failed_step,
        run_url=run_url,
        briefing_date=now.astimezone(KST).date().isoformat(),
        coverage=coverage,
    ))


def main() -> int:
    webhook = require("SLACK_WEBHOOK_URL")

    def read_last_sent() -> datetime | None:
        from pipeline.lib.store import SupabaseStore
        remote = SupabaseStore(require("SUPABASE_URL"), require("SUPABASE_SECRET_KEY"))
        return remote.last_sent_at()

    ok = report(
        # 워크플로가 넘긴다. 없으면 "어딘가"라도 알리는 쪽이 낫다.
        failed_step=optional("FAILED_STEP", "(알 수 없음)"),
        run_url=optional("RUN_URL", "(없음)"),
        now=datetime.now(timezone.utc),
        read_last_sent=read_last_sent,
        send=lambda lines: send_warnings(lines, webhook_url=webhook),
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
