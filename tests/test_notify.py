from datetime import datetime, timezone

import pytest

from pipeline.lib.retry import Permanent
from pipeline.models import (
    Article,
    Briefing,
    RankedBundle,
    RankedItem,
    RawBundle,
    RawItem,
    SourceError,
    Summary,
)
from pipeline.notify import AllSendersFailedError, AlreadySentError, notify
from tests.fakes import FakeRemoteStore, FakeSender

WINDOW_START = datetime(2026, 11, 9, 22, 20, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 11, 10, 22, 20, tzinfo=timezone.utc)
SENT_AT = datetime(2026, 11, 10, 22, 22, tzinfo=timezone.utc)


def _summary(index: int = 0) -> Summary:
    return Summary(
        article=Article(
            ranked=RankedItem(
                item=RawItem(
                    source="토스_기술블로그", title=f"원제 {index}",
                    url=f"https://toss.tech/a/{index}",
                    published="2026-11-10T05:30:00+00:00", excerpt="발췌",
                ),
                score=85, reason="이유", topic="backend",
            ),
            body="본문", body_source="trafilatura",
        ),
        headline=f"헤드라인 {index}",
        bullets=["요점"],
        why_it_matters="이유",
    )


def _briefing(summaries) -> Briefing:
    return Briefing(
        window_start=WINDOW_START.isoformat(),
        window_end=WINDOW_END.isoformat(),
        summaries=summaries,
        considered=10,
    )


def _raw(item_count: int = 42) -> RawBundle:
    return RawBundle(
        window_start=WINDOW_START.isoformat(),
        window_end=WINDOW_END.isoformat(),
        items=[
            RawItem(
                source="토스_기술블로그", title=f"수집 {i}",
                url=f"https://toss.tech/raw/{i}",
                published="2026-11-10T05:30:00+00:00", excerpt="발췌",
            )
            for i in range(item_count)
        ],
        source_counts={"토스_기술블로그": 3, "조용한소스": 0},
        errors=[SourceError(source="깨진소스", kind="config",
                            message="https://broken.com/r HTTP 404")],
    )


def _ranked(max_score: int | None = 94) -> RankedBundle:
    return RankedBundle(
        window_start=WINDOW_START.isoformat(),
        window_end=WINDOW_END.isoformat(),
        selected=[], all_scores=[], max_score=max_score,
    )


def _notify(briefing, senders=None, store=None, force=False, ranked=None, raw=None):
    remote = store or FakeRemoteStore()
    sent = senders if senders is not None else [FakeSender()]

    notify(
        briefing=briefing,
        ranked=ranked or _ranked(),
        raw=raw or _raw(),
        remote=remote,
        briefing_date="2026-11-10",
        senders=sent,
        force=force,
        now=SENT_AT,
    )
    return remote, sent


# --- 정상 경로 ---

def test_센더로_내보낸다():
    _, senders = _notify(_briefing([_summary()]))
    assert senders[0].calls == 1


def test_실행_이력을_남긴다():
    remote, _ = _notify(_briefing([_summary()]))

    assert len(remote.runs) == 1
    assert remote.runs[0]["published_count"] == 1
    assert remote.runs[0]["window_end"] == WINDOW_END


def test_발행_글을_저장한다():
    remote, _ = _notify(_briefing([_summary()]))

    assert len(remote.saved) == 1
    assert remote.saved[0]["briefing_date"] == "2026-11-10"


def test_소스별_건수를_이력에_남긴다():
    """소스 침묵 감지의 입력이다."""
    remote, _ = _notify(_briefing([_summary()]))
    assert remote.runs[0]["source_counts"] == {"토스_기술블로그": 3, "조용한소스": 0}


def test_에러의_성격까지_이력에_남긴다():
    """계획 3의 소스 경고가 "죽은 소스"와 "불안정한 소스"를 구분하는 근거다."""
    remote, _ = _notify(_briefing([_summary()]))
    assert remote.runs[0]["errors"][0]["kind"] == "config"


def test_수집_후보_최고점수를_이력에_남긴다():
    """0건인 날 화면이 "후보 10건 / 최고 54점 / 기준 60점"을 보여주는 데 쓴다.
    이 셋이 없으면 "기준이 높은가, 소스가 문제인가"를 판단할 수 없다."""
    remote, _ = _notify(_briefing([_summary()]), ranked=_ranked(max_score=54))
    run = remote.runs[0]

    assert run["collected_count"] == 42
    assert run["considered_count"] == 10
    assert run["max_score"] == 54


def test_성공한_실행은_sent_상태와_발송_시각을_남긴다():
    remote, _ = _notify(_briefing([_summary()]))

    assert remote.runs[0]["status"] == "sent"
    assert remote.runs[0]["sent_at"] == SENT_AT


def test_윈도우를_그대로_남긴다():
    """다음 실행의 윈도우 시작점이 된다. 어긋나면 구간이 겹치거나 빈다."""
    remote, _ = _notify(_briefing([_summary()]))

    assert remote.runs[0]["window_start"] == WINDOW_START
    assert remote.runs[0]["window_end"] == WINDOW_END


# --- 0건 ---

def test_0건이어도_내보내고_이력을_남긴다():
    """이력을 남기지 않으면 다음 윈도우가 계속 늘어난다."""
    remote, senders = _notify(_briefing([]))

    assert senders[0].calls == 1
    assert len(remote.runs) == 1
    assert remote.runs[0]["published_count"] == 0


def test_0건이면_글을_저장하지_않는다():
    remote, _ = _notify(_briefing([]))
    assert remote.saved == []


def test_0건이어도_윈도우가_전진한다():
    """파이프라인의 핵심 루프다. 전진하지 않으면 매번 같은 96시간을 다시 본다."""
    remote, _ = _notify(_briefing([]))
    assert remote.last_sent_at() == SENT_AT


# --- 멱등성 ---

def test_이미_보낸_윈도우는_다시_보내지_않는다():
    """cron 중복 실행이나 수동 재실행으로 두 번 오는 것을 막는다."""
    store = FakeRemoteStore(last_sent=WINDOW_END)

    with pytest.raises(AlreadySentError):
        _notify(_briefing([_summary()]), store=store)


def test_이미_보냈으면_센더를_부르지도_않는다():
    """막기만 하고 보내면 막은 의미가 없다."""
    store = FakeRemoteStore(last_sent=WINDOW_END)
    sender = FakeSender()

    with pytest.raises(AlreadySentError):
        _notify(_briefing([_summary()]), store=store, senders=[sender])

    assert sender.calls == 0


def test_더_늦은_발송_이력이_있으면_거부한다():
    later = datetime(2026, 11, 11, tzinfo=timezone.utc)
    with pytest.raises(AlreadySentError):
        _notify(_briefing([_summary()]), store=FakeRemoteStore(last_sent=later))


def test_force면_이미_보냈어도_다시_보낸다():
    store = FakeRemoteStore(last_sent=WINDOW_END)
    _, senders = _notify(_briefing([_summary()]), store=store, force=True)

    assert senders[0].calls == 1


def test_이전_윈도우의_이력은_막지_않는다():
    earlier = datetime(2026, 11, 9, 22, 20, tzinfo=timezone.utc)
    _, senders = _notify(_briefing([_summary()]),
                         store=FakeRemoteStore(last_sent=earlier))
    assert senders[0].calls == 1


# --- 센더 실패 ---

def test_센더가_여럿이면_하나가_죽어도_나머지는_보낸다():
    """계획 3에서 카톡 토큰이 만료돼도 슬랙은 가야 한다."""
    broken = FakeSender(name="broken", error=Permanent("HTTP 404"))
    working = FakeSender(name="working")

    remote, _ = _notify(_briefing([_summary()]), senders=[broken, working])

    assert working.calls == 1
    assert len(remote.runs) == 1          # 하나라도 갔으면 기록한다


def test_앞의_센더가_죽어도_뒤의_센더를_부른다():
    """순서에 의존하지 않는다."""
    broken = FakeSender(name="broken", error=Permanent("HTTP 404"))
    working = FakeSender(name="working")

    _notify(_briefing([_summary()]), senders=[broken, working])

    assert broken.calls == 1 and working.calls == 1


def test_하나라도_갔으면_실패한_센더를_이력에_남긴다():
    broken = FakeSender(name="broken", error=Permanent("HTTP 404"))
    remote, _ = _notify(_briefing([_summary()]),
                        senders=[broken, FakeSender(name="working")])

    errors = remote.runs[0]["errors"]
    assert any(error.get("source") == "sender:broken" for error in errors)


def _fail_all():
    """전부 실패하는 센더 둘로 notify를 돌리고 저장소를 돌려준다."""
    remote = FakeRemoteStore()
    senders = [FakeSender(name="a", error=Permanent("404")),
               FakeSender(name="b", error=Permanent("403"))]

    with pytest.raises(AllSendersFailedError) as 잡힘:
        notify(
            briefing=_briefing([_summary()]), ranked=_ranked(), raw=_raw(),
            remote=remote, briefing_date="2026-11-10", senders=senders,
            force=False, now=SENT_AT,
        )
    return remote, 잡힘.value


def test_전부_실패해도_실패_상태로_기록한다():
    """source_counts가 소스 침묵 경고의 유일한 입력이다. 실패한 날이
    기록에서 빠지면 그만큼 경고가 늦어진다."""
    remote, _ = _fail_all()

    assert len(remote.runs) == 1
    assert remote.runs[0]["status"] == "failed"
    assert remote.runs[0]["sent_at"] is None
    assert remote.runs[0]["source_counts"] == {"토스_기술블로그": 3, "조용한소스": 0}


def test_실패_메시지가_거짓말하지_않는다():
    """실행 기록은 status='failed'로 **남는다.** "이력을 남기지 않았다"고
    쓰면 다음 사람이 runs 테이블을 보고 혼란에 빠진다.
    """
    _, 예외 = _fail_all()
    메시지 = str(예외)

    assert "이력은 남지 않" not in 메시지
    assert "재실행" in 메시지


def test_전부_실패하면_글을_저장하지_않는다():
    remote, _ = _fail_all()
    assert remote.saved == []


def test_실패_기록이_재실행을_막지_않는다():
    """last_sent_at이 status='sent'만 보므로 막히지 않아야 한다."""
    remote, _ = _fail_all()

    assert remote.last_sent_at() is None

    # 원인을 고치고 그대로 재실행
    working = FakeSender(name="working")
    notify(
        briefing=_briefing([_summary()]), ranked=_ranked(), raw=_raw(),
        remote=remote, briefing_date="2026-11-10", senders=[working],
        force=False, now=SENT_AT,
    )

    assert working.calls == 1
    assert remote.last_sent_at() == SENT_AT


def test_실패한_센더를_이력의_에러에_남긴다():
    remote, _ = _fail_all()
    names = [error.get("source") for error in remote.runs[0]["errors"]]

    assert "sender:a" in names
    assert "sender:b" in names


def test_센더가_하나도_없으면_거부한다():
    """설정 실수로 조용히 아무 데도 안 보내는 것을 막는다."""
    with pytest.raises(ValueError, match="센더"):
        _notify(_briefing([_summary()]), senders=[])


# --- 저장 실패 ---
#
# 전송은 됐는데 DB 저장이 실패하는 경우. 여기서 예외를 올려 버리면 실행
# 기록이 남지 않고, 재실행이 **이미 보낸 브리핑을 다시 보낸다.**
# 사용자에게 두 번 가는 것이 페이지가 비는 것보다 나쁘다.

def test_저장이_실패해도_실행_기록은_남긴다():
    store = FakeRemoteStore(save_error=RuntimeError("DB 연결 끊김"))
    remote, _ = _notify(_briefing([_summary()]), store=store)

    assert len(remote.runs) == 1
    assert remote.runs[0]["status"] == "sent"


def test_저장_실패를_이력의_에러에_남긴다():
    store = FakeRemoteStore(save_error=RuntimeError("DB 연결 끊김"))
    remote, _ = _notify(_briefing([_summary()]), store=store)

    errors = remote.runs[0]["errors"]
    assert any(error.get("source") == "save_articles" for error in errors)
    assert any("DB 연결 끊김" in error.get("message", "") for error in errors)


def test_저장이_실패해도_윈도우는_전진한다():
    """전진하지 않으면 다음 실행이 같은 브리핑을 또 보낸다."""
    store = FakeRemoteStore(save_error=RuntimeError("DB 연결 끊김"))
    remote, _ = _notify(_briefing([_summary()]), store=store)

    assert remote.last_sent_at() == SENT_AT
