"""단계 실패 보고 테스트.

실패 보고의 핵심은 "지금 손으로 다시 돌려야 하나?"에 답하는 것이다.
수집 윈도우는 `max(마지막 발송, 지금 − 96시간)`이라, 다음 정기 실행이 놓친
기간을 다 덮는지는 **날짜에 따라 다르다.** 계획서 원안은 "다음 날이 이틀치를
덮으니 그냥 둬도 된다"고 고정 문구를 썼다 — 금요일엔 다음이 월요일이고,
이틀 연속 실패하면 하루치가 영영 빠진다.
"""

from datetime import datetime, timedelta, timezone

from pipeline.lib.timeutil import KST
from pipeline.report_failure import build_report, coverage_note, next_scheduled_run, report


def kst(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=KST)


# --- 다음 정기 실행 ---
# 2026-11-16은 월요일이다.

def test_오늘_실행_전이면_오늘_07시20분():
    assert next_scheduled_run(kst(2026, 11, 17, 6, 0)) == kst(2026, 11, 17, 7, 20)


def test_오늘_실행_뒤면_내일():
    assert next_scheduled_run(kst(2026, 11, 17, 7, 40)) == kst(2026, 11, 18, 7, 20)


def test_금요일_실행_뒤면_월요일():
    assert next_scheduled_run(kst(2026, 11, 20, 7, 40)) == kst(2026, 11, 23, 7, 20)


def test_주말이면_월요일():
    assert next_scheduled_run(kst(2026, 11, 21, 12, 0)) == kst(2026, 11, 23, 7, 20)


# --- 다음 실행이 덮는가 ---

def test_평일_하루_실패는_다음_날이_덮는다():
    # 화요일 실행 실패. 마지막 발송은 월요일 07:23.
    note = coverage_note(last_sent_at=kst(2026, 11, 16, 7, 23), now=kst(2026, 11, 17, 7, 30))

    assert "11/18" in note and "다 덮는다" in note
    assert "다시 돌" not in note


def test_금요일_실패는_월요일이_간신히_덮는다():
    """목요일 07:23 발송 → 금요일 실패 → 월요일 07:20의 96시간 전은 목요일 07:20.
    3분 여유다. 실행이 늦게 시작하면(Actions cron은 흔히 늦다) 그만큼 빠진다."""
    note = coverage_note(last_sent_at=kst(2026, 11, 19, 7, 23), now=kst(2026, 11, 20, 7, 30))

    assert "11/23" in note
    assert "3분" in note and "늦게" in note


def test_이틀_연속_실패면_빠지는_시간을_말하고_다시_돌리라고_한다():
    """수요일 07:23 발송 → 목·금 실패 → 월요일은 목요일 07:20까지만 거슬러 본다.
    수요일 07:23 ~ 목요일 07:20, 약 24시간 분량이 영영 빠진다."""
    note = coverage_note(last_sent_at=kst(2026, 11, 18, 7, 23), now=kst(2026, 11, 20, 7, 30))

    assert "23시간" in note or "24시간" in note
    assert "다시 돌" in note


def test_보낸_적이_없으면_그렇게_말한다():
    note = coverage_note(last_sent_at=None, now=kst(2026, 11, 17, 7, 30))

    assert "보낸 적" in note


# --- 보고 ---

def test_어느_단계에서_언제_죽었는지와_로그를_준다():
    lines = build_report(
        failed_step="rank",
        run_url="https://github.com/x/y/actions/runs/123",
        briefing_date="2026-11-17",
        coverage="다음 정기 실행이 다 덮는다.",
    )
    text = "\n".join(lines)

    assert "rank" in text and "2026-11-17" in text
    assert "actions/runs/123" in text
    assert "다 덮는다" in text


def test_DB를_못_읽어도_보고는_간다():
    """실패 원인이 DB일 수 있다. 그때 보고까지 죽으면 아무것도 모른다."""
    sent = []

    def broken():
        raise RuntimeError("Supabase 503")

    ok = report(
        failed_step="collect", run_url="https://x/1", now=kst(2026, 11, 17, 7, 30),
        read_last_sent=broken, send=lambda lines: sent.append(lines) or True,
    )

    assert ok is True
    text = "\n".join(sent[0])
    assert "collect" in text
    assert "마지막 발송" in text and "못 읽" in text


def test_정상이면_계산한_판단을_싣는다():
    sent = []

    ok = report(
        failed_step="notify", run_url="https://x/1", now=kst(2026, 11, 17, 7, 30),
        read_last_sent=lambda: kst(2026, 11, 16, 7, 23).astimezone(timezone.utc),
        send=lambda lines: sent.append(lines) or True,
    )

    assert ok is True
    assert any("다 덮는다" in line for line in sent[0])


def test_슬랙이_실패하면_False():
    ok = report(
        failed_step="notify", run_url="https://x/1", now=kst(2026, 11, 17, 7, 30),
        read_last_sent=lambda: None, send=lambda lines: False,
    )

    assert ok is False
