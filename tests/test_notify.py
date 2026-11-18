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
    TokenUsage,
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


# --- 토큰 합산 ---
#
# 크레딧 가드(계획 3)가 runs에서 읽는다. 분기가 셋이라 전부 본다.

def _with_tokens(bundle, input_: int, output: int):
    """번들에 토큰을 실어 돌려준다. Contract가 frozen이라 복사로 만든다."""
    return bundle.model_copy(update={"tokens": TokenUsage(input=input_, output=output)})


def test_두_단계의_토큰을_합쳐_기록한다():
    remote = FakeRemoteStore()

    notify(
        briefing=_with_tokens(_briefing([_summary()]), 8000, 2400),
        ranked=_with_tokens(_ranked(), 42135, 1820),
        raw=_raw(),
        remote=remote,
        briefing_date="2026-11-10",
        senders=[FakeSender("ok")],
        now=SENT_AT,
    )

    assert remote.runs[0]["input_tokens"] == 50135
    assert remote.runs[0]["output_tokens"] == 4220


def test_한쪽만_있으면_그쪽만_센다():
    """수집이 0건이면 rank가 LLM을 부르지 않아 ranked.tokens가 None이다.
    그때 summarize 것만 세는 것이 맞다.
    """
    remote = FakeRemoteStore()

    notify(
        briefing=_with_tokens(_briefing([_summary()]), 8000, 2400),
        ranked=_ranked(),                      # tokens 없음
        raw=_raw(),
        remote=remote,
        briefing_date="2026-11-10",
        senders=[FakeSender("ok")],
        now=SENT_AT,
    )

    assert remote.runs[0]["input_tokens"] == 8000
    assert remote.runs[0]["output_tokens"] == 2400


def test_둘_다_없으면_None으로_남긴다():
    """0으로 적으면 크레딧 가드가 "안 썼다"로 읽어 거짓 안심을 한다.
    "모른다"와 "0"은 다르다.
    """
    remote = FakeRemoteStore()

    notify(
        briefing=_briefing([_summary()]),
        ranked=_ranked(),
        raw=_raw(),
        remote=remote,
        briefing_date="2026-11-10",
        senders=[FakeSender("ok")],
        now=SENT_AT,
    )

    assert remote.runs[0]["input_tokens"] is None
    assert remote.runs[0]["output_tokens"] is None


# --- 가드 조립 (계획 3 Task 12) ---

from datetime import date, timedelta

from pipeline.lib.config import Source
from pipeline.notify import guard_warnings, read_budget

GUARD_NOW = datetime(2026, 11, 17, 22, 20, tzinfo=timezone.utc)
TODAY = date(2026, 11, 18)


def _source(name: str, tier: str = "fast") -> Source:
    return Source(name=name, url=f"https://e.com/{name}", kind="rss",
                  weight=1.0, lang="ko", quiet_tier=tier)


def _guard(remote=None, *, sources=(), today_counts=None, today_input=0,
           budget=None, seed=None):
    return guard_warnings(
        remote=remote or FakeRemoteStore(),
        sources=list(sources),
        today=TODAY,
        today_counts=today_counts or {},
        today_input=today_input,
        budget_usd=budget,
        now=GUARD_NOW,
        seed=seed or {},
    )


def test_조용한_소스를_경과일과_기준으로_알린다():
    remote = FakeRemoteStore()
    remote.runs_history = [
        {"briefing_date": "2026-11-17", "source_counts": {"토스": 0}},
        {"briefing_date": "2026-09-01", "source_counts": {"토스": 3}},
    ]

    lines = _guard(remote, sources=[_source("토스")])

    assert lines == ["소스 침묵: 토스 — 78일째 (기준 30일)"]


def test_오늘_글이_왔으면_침묵_경고를_내지_않는다():
    """가드는 오늘 실행 기록을 남기기 **전에** 돈다. 오늘 수집분을 넣지 않으면
    30일 조용하던 소스가 오늘 글을 썼는데도 오늘 아침 "30일째"가 뜬다."""
    remote = FakeRemoteStore()
    remote.runs_history = [{"briefing_date": "2026-09-01", "source_counts": {"토스": 3}}]

    lines = _guard(remote, sources=[_source("토스")], today_counts={"토스": 2})

    assert lines == []


def test_토큰_만료가_가까우면_재발급_방법과_함께_알린다():
    remote = FakeRemoteStore()
    remote.kakao = ("RT", GUARD_NOW + timedelta(days=10))

    [line] = _guard(remote)

    assert "10일 남음" in line
    assert "scripts/kakao_auth.py" in line


def test_토큰이_이미_만료됐으면_지났다고_알린다():
    remote = FakeRemoteStore()
    remote.kakao = ("RT", GUARD_NOW - timedelta(days=3))

    [line] = _guard(remote)

    assert "3일 지남" in line


def test_예산의_80퍼센트를_넘으면_알린다():
    remote = FakeRemoteStore()
    remote.runs_history = [
        {"briefing_date": "2026-11-03", "source_counts": {},
         "input_tokens": 3_000_000, "output_tokens": 600_000},   # $12 + $12 = $24
    ]

    [line] = _guard(remote, budget=30.0)

    assert "$24.00" in line and "$30" in line


def test_지난달_사용량은_이번_달_예산에_넣지_않는다():
    remote = FakeRemoteStore()
    remote.runs_history = [
        {"briefing_date": "2026-10-31", "source_counts": {},
         "input_tokens": 3_000_000, "output_tokens": 600_000},
    ]

    assert _guard(remote, budget=30.0) == []


def test_비용을_모르면_예산_경고를_내지_않고_터지지도_않는다():
    """Task 11에서 month_cost_usd가 "모른다"면 None을 돌려주게 했다. 계획서
    원안은 `spent >= 예산`으로 바로 비교해서, 토큰 기록이 없는 지금(2026-11-18
    실측: runs 3행 모두 비어 있다) TypeError로 가드 전체가 죽는다."""
    remote = FakeRemoteStore()
    remote.runs_history = [{"briefing_date": "2026-11-12", "source_counts": {},
                            "input_tokens": None, "output_tokens": None}]

    assert _guard(remote, budget=30.0) == []


def test_예산이_없으면_예산_경고만_건너뛴다():
    remote = FakeRemoteStore()
    remote.runs_history = [{"briefing_date": "2026-11-03", "source_counts": {},
                            "input_tokens": 9_000_000, "output_tokens": 9_000_000}]

    assert _guard(remote, budget=None) == []


def test_입력_토큰이_평소의_3배를_넘으면_알린다():
    remote = FakeRemoteStore()
    remote.runs_history = [
        {"briefing_date": f"2026-11-{d:02d}", "source_counts": {},
         "input_tokens": 80_000, "output_tokens": 20_000}
        for d in range(3, 13)
    ]

    [line] = _guard(remote, today_input=250_000)

    assert "250,000" in line


def test_예산_값을_읽는다():
    problems = []

    assert read_budget("30", problems.append) == 30.0
    assert read_budget(None, problems.append) is None
    assert read_budget("", problems.append) is None
    assert problems == []


def test_예산_값이_숫자가_아니면_경고하고_없는_것으로_본다():
    """오타로 예산 경고가 조용히 꺼지면 안 된다. 꺼진 사실을 알린다."""
    problems = []

    assert read_budget("$30", problems.append) is None
    assert len(problems) == 1 and "MONTHLY_BUDGET_USD" in problems[0]


# --- notify가 가드와 실패를 경고로 낸다 ---

from pipeline.lib.kakao import KakaoTokens
from pipeline.lib.retry import Transient
from pipeline.lib.sender import KakaoSender
from pipeline.notify import build_kakao_sender, send_warnings


def _notify_warned(*, remote=None, senders=None, briefing=None, sources=(), warn=None):
    warned: list[str] = []
    notify(
        briefing=briefing or _briefing([_summary()]),
        ranked=_ranked(),
        raw=_raw(),
        remote=remote or FakeRemoteStore(),
        briefing_date="2026-11-10",
        senders=senders if senders is not None else [FakeSender()],
        now=SENT_AT,
        warn=warn or warned.append,
        sources=list(sources),
    )
    return warned


def test_가드_경고가_warn으로_간다():
    """브리핑은 카톡으로, 경고는 슬랙으로. 섞이지 않는다."""
    remote = FakeRemoteStore()
    remote.runs_history = [{"briefing_date": "2026-08-01", "source_counts": {"토스": 3}}]

    warned = _notify_warned(remote=remote, sources=[_source("토스")])

    assert any(w.startswith("소스 침묵: 토스") for w in warned)


def test_가드가_터져도_브리핑은_나간다():
    """경고 때문에 브리핑이 막히면 주객이 전도된다."""
    class Broken(FakeRemoteStore):
        def recent_runs(self, days):
            raise RuntimeError("DB가 잠깐 죽었다")

    sender = FakeSender()
    remote = Broken()
    _notify_warned(remote=remote, senders=[sender], sources=[_source("토스")])

    assert sender.calls == 1
    assert remote.runs[-1]["status"] == "sent"


def test_경고_채널이_터져도_브리핑은_나간다():
    def exploding(_):
        raise RuntimeError("슬랙이 죽었다")

    sender = FakeSender()
    remote = FakeRemoteStore()
    remote.runs_history = [{"briefing_date": "2026-08-01", "source_counts": {"토스": 3}}]
    _notify_warned(remote=remote, senders=[sender], sources=[_source("토스")], warn=exploding)

    assert sender.calls == 1


def test_카톡_발송이_실패하면_경고로_알린다():
    """ConsoleSender는 항상 성공하므로 카톡이 실패해도 실행은 'sent'로 끝난다.
    실패는 runs.errors에만 남고 아무도 모른다. 카톡이 안 갔을 때 알리는 것이
    슬랙의 존재 이유다."""
    warned = _notify_warned(senders=[
        FakeSender(name="console"),
        FakeSender(name="kakao", error=Permanent("카카오 발송 HTTP 401")),
    ])

    assert any("kakao" in w and "401" in w for w in warned)


def test_페이지_저장이_실패하면_경고로_알린다():
    warned = _notify_warned(remote=FakeRemoteStore(save_error=RuntimeError("timeout")))

    assert any("페이지" in w for w in warned)


def test_이미_보냈으면_경고도_내지_않는다():
    """재실행이 같은 경고를 또 보내면 그것도 알림 피로다."""
    warned: list[str] = []
    with pytest.raises(AlreadySentError):
        notify(
            briefing=_briefing([_summary()]), ranked=_ranked(), raw=_raw(),
            remote=FakeRemoteStore(last_sent=WINDOW_END), briefing_date="2026-11-10",
            senders=[FakeSender()], now=SENT_AT, warn=warned.append, sources=[_source("토스")],
        )

    assert warned == []


# --- 카톡 센더 조립 ---

KAKAO_NOW = datetime(2026, 12, 20, 22, 20, tzinfo=timezone.utc)


def _build(remote, exchange):
    warned: list[str] = []
    sender = build_kakao_sender(
        remote=remote, client_id="ID", client_secret="SECRET",
        page_url="https://x.test", now=KAKAO_NOW, warn=warned.append, exchange=exchange,
    )
    return sender, warned


def test_토큰이_없으면_카톡_없이_가고_알린다():
    """계획서 원안은 토큰이 없으면 카톡을 조용히 빼기만 했다. 매일 콘솔에만
    찍히고 아무도 모른다."""
    sender, warned = _build(FakeRemoteStore(), exchange=None)

    assert sender is None
    assert len(warned) == 1 and "scripts/kakao_auth.py" in warned[0]


def test_토큰_갱신이_실패하면_카톡_없이_가고_알린다():
    """**슬랙이 있는 이유가 정확히 이 순간이다.** 원안은 여기서 예외가 나
    실행 전체가 멈췄다 — 브리핑 기록도 슬랙 경고도 없이."""
    remote = FakeRemoteStore()
    remote.kakao = ("RT", KAKAO_NOW)

    def expired(**_):
        raise Permanent("카카오 토큰 HTTP 401 — invalid_grant")

    sender, warned = _build(remote, exchange=expired)

    assert sender is None
    assert "갱신 실패" in warned[0] and "invalid_grant" in warned[0]
    assert "scripts/kakao_auth.py" in warned[0]


def test_일시적_갱신_실패도_카톡_없이_간다():
    remote = FakeRemoteStore()
    remote.kakao = ("RT", KAKAO_NOW)

    def flaky(**_):
        raise Transient("카카오 토큰 시간 초과")

    sender, warned = _build(remote, exchange=flaky)

    assert sender is None and "시간 초과" in warned[0]


def test_회전된_토큰을_저장하고_보낸다():
    remote = FakeRemoteStore()
    remote.kakao = ("OLD", KAKAO_NOW + timedelta(days=20))

    def rotated(**kw):
        assert kw["refresh_token"] == "OLD"
        return KakaoTokens(access_token="AT", refresh_token="NEW",
                           refresh_token_expires_in=5184000)

    sender, warned = _build(remote, exchange=rotated)

    assert isinstance(sender, KakaoSender)
    assert remote.saved_tokens == [("NEW", KAKAO_NOW + timedelta(days=60))]
    assert warned == []


def test_회전_저장이_실패해도_오늘은_보내고_알린다():
    """오늘 access_token은 받았으니 오늘은 보낸다. 다만 새 토큰을 잃었으므로
    사람이 알아야 한다 — 내버려 두면 한 달 뒤 조용히 끊긴다."""
    remote = FakeRemoteStore()
    remote.kakao = ("OLD", KAKAO_NOW + timedelta(days=20))
    remote.kakao_save_error = RuntimeError("DB timeout")

    def rotated(**_):
        return KakaoTokens(access_token="AT", refresh_token="NEW",
                           refresh_token_expires_in=5184000)

    sender, warned = _build(remote, exchange=rotated)

    assert isinstance(sender, KakaoSender)
    assert len(warned) == 1 and "저장" in warned[0]


def test_평소에는_보내기만_한다():
    remote = FakeRemoteStore()
    remote.kakao = ("RT", KAKAO_NOW + timedelta(days=50))

    sender, warned = _build(remote, exchange=lambda **_: KakaoTokens(access_token="AT"))

    assert isinstance(sender, KakaoSender)
    assert remote.saved_tokens == [] and warned == []


# --- 슬랙으로 내보내기 ---

def test_경고가_없으면_슬랙을_부르지_않는다():
    calls = []
    assert send_warnings([], webhook_url="https://hooks.test/x",
                         post=lambda *a, **k: calls.append(1) or "ok") is True
    assert calls == []


def test_경고를_한_번에_보낸다():
    calls = []

    def post(url, *, payload, timeout, label):
        calls.append(payload["text"])
        return "ok"

    assert send_warnings(["가", "나"], webhook_url="https://hooks.test/x", post=post) is True
    assert len(calls) == 1 and "가" in calls[0] and "나" in calls[0]


def test_슬랙이_실패하면_로그에_경고를_남기고_실패를_알린다(capsys):
    """슬랙마저 실패하면 경고가 갈 곳이 Actions 로그뿐이다. 거기라도 남기고,
    False를 돌려 실행이 실패로 끝나게 한다 — GitHub가 실패 메일을 보낸다."""
    def broken(*a, **k):
        raise Permanent("Slack webhook HTTP 404 — no_service")

    assert send_warnings(["소스 침묵: 토스"], webhook_url="https://hooks.test/x",
                         post=broken) is False
    err = capsys.readouterr().err
    assert "소스 침묵: 토스" in err and "no_service" in err


def test_예산을_반올림하지_않고_적는다():
    """원래 `:.0f`라 예산 $12.5가 "$12"로, $0.01이 "$0"으로 보였다
    (2026-11-18 가드 훈련에서 발견)."""
    remote = FakeRemoteStore()
    remote.runs_history = [{"briefing_date": "2026-11-03", "source_counts": {},
                            "input_tokens": 3_000_000, "output_tokens": 0}]   # $12

    [line] = _guard(remote, budget=12.5)

    assert "$12.5" in line
