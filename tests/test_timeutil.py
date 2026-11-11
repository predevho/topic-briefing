from datetime import datetime, timedelta, timezone

import pytest

from pipeline.lib.timeutil import (
    KST,
    MAX_WINDOW_HOURS,
    SEND_CRON_UTC,
    SEND_HOUR_UTC,
    SEND_MINUTE_UTC,
    compute_window,
    to_utc_iso,
)

WEEKDAY_NAMES = "월화수목금토일"


def _kst_weekdays_for_cron_days(first_utc_day: int) -> list[str]:
    """UTC로 연속 5일 발송했을 때의 KST 요일을 돌려준다.

    2026-11-08이 일요일이므로, first_utc_day=8이면 cron 요일 0-4(일~목)에
    해당한다.
    """
    return [
        WEEKDAY_NAMES[
            datetime(
                2026, 11, first_utc_day + offset,
                SEND_HOUR_UTC, SEND_MINUTE_UTC, tzinfo=timezone.utc,
            ).astimezone(KST).weekday()
        ]
        for offset in range(5)
    ]


# --- 시각 정규화 ---

def test_RFC822_표기를_UTC로_정규화한다():
    """국내 매체 RSS에서 흔한 형식."""
    assert to_utc_iso("Tue, 10 Nov 2026 14:30:00 +0900") == "2026-11-10T05:30:00+00:00"


def test_ISO8601_Z_표기를_정규화한다():
    assert to_utc_iso("2026-11-10T05:30:00Z") == "2026-11-10T05:30:00+00:00"


def test_오프셋이_있는_ISO8601을_정규화한다():
    assert to_utc_iso("2026-11-10T14:30:00+09:00") == "2026-11-10T05:30:00+00:00"


def test_타임존이_없으면_UTC로_간주한다():
    """표기가 없는 피드가 실제로 있다. 추측하지 않고 UTC로 고정한다."""
    assert to_utc_iso("2026-11-10T05:30:00") == "2026-11-10T05:30:00+00:00"


def test_파싱할_수_없으면_None을_돌려준다():
    """한 건의 날짜 오류로 수집 전체가 죽지 않게 한다."""
    assert to_utc_iso("언젠가") is None
    assert to_utc_iso("") is None
    assert to_utc_iso(None) is None


# --- 수집 윈도우 ---

def test_마지막_발송_시각부터_지금까지가_윈도우가_된다():
    now = datetime(2026, 11, 10, 22, 20, tzinfo=timezone.utc)
    last = datetime(2026, 11, 9, 22, 20, tzinfo=timezone.utc)

    start, end = compute_window(now=now, last_sent_at=last)

    assert start == last
    assert end == now


def test_주말을_쉰_월요일은_약_72시간이_된다():
    """금요일 발송 후 월요일 실행. 주말 해외 콘텐츠가 포함된다."""
    friday_sent = datetime(2026, 11, 6, 22, 20, tzinfo=timezone.utc)
    monday_now = datetime(2026, 11, 9, 22, 20, tzinfo=timezone.utc)

    start, end = compute_window(now=monday_now, last_sent_at=friday_sent)

    assert (end - start) == timedelta(hours=72)


def test_윈도우가_96시간을_넘지_않는다():
    """장애로 2주 멈춘 뒤 복구되어도 수집량이 폭증하지 않게 한다."""
    now = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)
    long_ago = now - timedelta(days=14)

    start, end = compute_window(now=now, last_sent_at=long_ago)

    assert (end - start) == timedelta(hours=MAX_WINDOW_HOURS)
    assert start == now - timedelta(hours=MAX_WINDOW_HOURS)


def test_발송_이력이_없으면_상한만큼_거슬러_올라간다():
    """최초 실행."""
    now = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)

    start, end = compute_window(now=now, last_sent_at=None)

    assert (end - start) == timedelta(hours=MAX_WINDOW_HOURS)


def test_윈도우_경계가_타임존_없는_값을_거부한다():
    """naive datetime을 섞으면 비교가 조용히 틀린다. 즉시 죽인다."""
    naive = datetime(2026, 11, 10, 0, 0)

    with pytest.raises(ValueError, match="타임존"):
        compute_window(now=naive, last_sent_at=None)


def test_KST가_UTC_플러스_9시간이다():
    assert KST.utcoffset(None) == timedelta(hours=9)


# --- 발송 요일 ---

def test_발송_cron이_KST_월금에_해당한다():
    """이 테스트가 없으면 요일이 한 칸 밀린 것을 수동 관찰로만 알 수 있다.

    증상이 "일주일에 한 번 이상한 날에 온다"라서 알아차리기까지 오래 걸린다.
    """
    assert SEND_CRON_UTC == "20 22 * * 0-4"

    # cron 0-4 = UTC 일~목. 2026-11-08이 일요일이다.
    assert _kst_weekdays_for_cron_days(8) == ["월", "화", "수", "목", "금"]


def test_cron_요일을_하나_밀면_월요일이_빠지고_토요일에_발송된다():
    """위 테스트가 실제로 무엇을 막는지 보여준다.

    cron을 1-5(UTC 월~금)로 쓰면 KST로는 화~토가 된다. 월요일은 주말
    해외 콘텐츠를 72시간 윈도우로 받는 날이라 가장 손실이 크다.
    """
    shifted = _kst_weekdays_for_cron_days(9)   # UTC 월요일부터

    assert shifted == ["화", "수", "목", "금", "토"]
    assert "월" not in shifted
