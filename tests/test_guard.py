"""소스 침묵 가드 테스트.

지표는 "N일 연속 0건"이 아니라 **마지막으로 글이 보인 날로부터 경과일**이다.
0건은 수집 윈도우(최대 96시간) 기준이라 주간 소스는 7일 중 5일이 0건이다.
"""

import json
from datetime import date

from pipeline.lib.config import Source
from pipeline.lib.guard import (
    QUIET_THRESHOLDS,
    days_since_seen,
    load_seed_last_seen,
    silent_sources,
)

TODAY = date(2026, 11, 17)


def _source(name: str, tier: str) -> Source:
    return Source(
        name=name,
        url=f"https://e.com/{name}",
        kind="rss",
        weight=1.0,
        lang="ko",
        quiet_tier=tier,
    )


def _run(day: str, counts: dict) -> dict:
    return {"briefing_date": day, "source_counts": counts}


# --- 경과일 ---

def test_마지막으로_본_날로부터_센다():
    runs = [
        _run("2026-11-17", {"토스": 0}),
        _run("2026-11-16", {"토스": 0}),
        _run("2026-11-15", {"토스": 2}),
    ]

    assert days_since_seen(runs, "토스", today=TODAY) == 2


def test_순서와_무관하게_가장_최근을_본다():
    """원안은 runs가 내림차순이라고 **가정**하고 첫 양수를 돌려줬다.
    질의가 정렬을 빠뜨리면 오래된 날짜를 집어 거짓 경고가 뜬다.
    전제를 없앤다 — 양수인 날 중 가장 늦은 날을 쓴다.
    """
    runs = [
        _run("2026-10-01", {"토스": 3}),
        _run("2026-11-15", {"토스": 1}),
        _run("2026-11-17", {"토스": 0}),
    ]

    assert days_since_seen(runs, "토스", today=TODAY) == 2


def test_빈_실행_기록에_속지_않는다():
    """2026-11-12에 실제 실행 1행(240건)과 빈 행 2행(0건)이 함께 있다
    (계획 1 개발 중 --force의 흔적). 0인 행은 "못 봤다"일 뿐 "죽었다"가
    아니다 — 양수인 날만 센다.
    """
    runs = [
        _run("2026-11-12", {"토스": 4}),
        _run("2026-11-12", {"토스": 0}),
        _run("2026-11-12", {}),
    ]

    assert days_since_seen(runs, "토스", today=TODAY) == 5


def test_한_번도_못_봤으면_None이다():
    """시드에도 없고 runs에도 없으면 새로 넣은 소스다. 죽었다고 하면 오탐이다."""
    runs = [_run("2026-11-17", {"토스": 1})]

    assert days_since_seen(runs, "새소스", today=TODAY) is None


def test_runs에서_못_봤으면_시드의_마지막_날로_센다():
    """**원안의 빈틈.** runs는 2026-11-12부터만 있다. 그 전부터 조용하던
    소스는 runs에서 영원히 None이 되어 **절대 경고하지 않는다.**

    2026-11-17 실측: 11/12 실행에서 45개 중 16개가 0건이었고, 그중
    하이퍼커넥트는 시드상 마지막 글이 209일 전이다(등급 monthly, 기준 200일).
    지금 경고가 떠야 하는데 원안으로는 안 뜬다.
    """
    runs = [_run("2026-11-12", {"하이퍼커넥트": 0})]
    seed = {"하이퍼커넥트": date(2026, 4, 22)}

    assert days_since_seen(runs, "하이퍼커넥트", today=TODAY, seed=seed) == 209


def test_runs와_시드_중_늦은_쪽을_쓴다():
    """시드 뒤에 다시 글이 왔으면 runs가 이긴다."""
    runs = [_run("2026-11-15", {"토스": 1})]
    seed = {"토스": date(2026, 9, 1)}

    assert days_since_seen(runs, "토스", today=TODAY, seed=seed) == 2


# --- 임계값 ---

def test_등급마다_임계값이_다르다():
    assert QUIET_THRESHOLDS["fast"] == 30
    assert QUIET_THRESHOLDS["weekly"] == 90
    assert QUIET_THRESHOLDS["monthly"] == 200
    assert QUIET_THRESHOLDS["none"] is None


def test_none_등급은_경고하지_않는다():
    """400일에 2편인 소스를 400일 기준으로 감시하는 건 가드가 아니라
    가드인 척이다. 그 한 줄이 잘못된 안심을 준다.
    """
    sources = [_source("Lil_Log", tier="none")]
    seed = {"Lil_Log": date(2026, 7, 4)}          # 136일 전

    assert silent_sources(sources, [], today=TODAY, seed=seed) == []


def test_한_번도_못_본_소스는_경고하지_않는다():
    runs = [_run("2026-11-17", {"빠른소스": 0, "주간소스": 0})]
    sources = [_source("빠른소스", tier="fast"), _source("주간소스", tier="weekly")]

    assert silent_sources(sources, runs, today=TODAY) == []


def test_경과일과_임계값을_함께_알려준다():
    """'토스가 조용하다'보다 '토스 45일째 (기준 30일)'가 조치로 이어진다.
    기준을 올릴지 소스를 끌지 판단할 수 있다.
    """
    runs = [
        _run("2026-11-17", {"토스": 0}),
        _run("2026-10-03", {"토스": 1}),
    ]
    sources = [_source("토스", tier="fast")]

    assert silent_sources(sources, runs, today=TODAY) == [("토스", 45, 30)]


def test_임계값_바로_전날은_조용하다():
    runs = [_run("2026-10-19", {"토스": 1})]       # 29일 전
    sources = [_source("토스", tier="fast")]

    assert silent_sources(sources, runs, today=TODAY) == []


# --- 시드 파일 ---

def test_시드_파일을_날짜로_읽는다(tmp_path):
    path = tmp_path / "seed.json"
    path.write_text(json.dumps({
        "_note": "설명",
        "seed_date": "2026-11-12",
        "last_seen": {"토스": "2026-11-10", "하이퍼커넥트": "2026-04-22"},
    }), encoding="utf-8")

    seed = load_seed_last_seen(path)

    assert seed == {"토스": date(2026, 11, 10), "하이퍼커넥트": date(2026, 4, 22)}


def test_시드_파일이_없으면_빈_것으로_본다(tmp_path):
    """파일이 없다고 파이프라인을 멈추지 않는다. 시드 없이도 runs로 돈다 —
    다만 그 전부터 조용하던 소스를 못 잡을 뿐이다."""
    assert load_seed_last_seen(tmp_path / "없음.json") == {}


def test_커밋된_시드_파일이_말이_된다():
    """config/seed_last_seen.json — scripts/seed_last_seen.py가 만든다.
    날짜가 시드 수집일보다 늦으면 계산이 틀린 것이다."""
    seed = load_seed_last_seen()

    assert len(seed) >= 40
    assert all(day <= date(2026, 11, 12) for day in seed.values())


# --- 토큰 만료 ---
#
# 카카오 refresh_token은 60일이다(2026-11-17 실측). 만료가 1개월 미만이면
# 갱신 때 새 토큰이 오고, 그걸 저장하면 수명이 다시 60일로 늘어난다.
# 그래서 **정상이면 남은 일수가 30일 아래로 거의 내려가지 않는다.** 14일 경고는
# 회전 저장이 2주 넘게 실패했거나 파이프라인이 한 달 넘게 멈췄다는 뜻이다.

from datetime import datetime, timedelta, timezone

from pipeline.lib.guard import TOKEN_WARN_DAYS, token_expiring

NOW = datetime(2026, 11, 17, 22, 20, tzinfo=timezone.utc)


def test_14일_안이면_알린다():
    assert token_expiring(NOW + timedelta(days=10), now=NOW) == 10


def test_정확히_14일이면_알린다():
    assert token_expiring(NOW + timedelta(days=14), now=NOW) == 14


def test_여유가_있으면_알리지_않는다():
    """매일 알리면 그게 알림 피로다. 60일 남은 날에는 조용해야 한다."""
    assert token_expiring(NOW + timedelta(days=60), now=NOW) is None
    assert token_expiring(NOW + timedelta(days=15), now=NOW) is None


def test_이미_만료됐으면_음수로_알린다():
    """'3일 지났다'가 '0일 남았다'보다 정확하다. 이미 끊긴 상태와 곧 끊길
    상태는 다른 조치를 부른다."""
    assert token_expiring(NOW - timedelta(days=3), now=NOW) == -3


def test_임계값이_14일이다():
    """재인증은 브라우저에서 사람이 해야 한다. 2주면 주말을 두 번 지난다."""
    assert TOKEN_WARN_DAYS == 14


# --- 크레딧 ---
#
# Anthropic은 잔여 크레딧을 알려주지 않는다. /cost는 "할인 후, 크레딧 적용 전"
# 금액이고 Admin 키와 4~24시간 지연이 따른다. 그래서 우리 사용량을 누적해
# 내가 정한 예산과 비교한다(설계 0.1).

import pytest

from pipeline.lib.guard import (
    BUDGET_WARN_RATIO,
    PRICES,
    SPIKE_FACTOR,
    month_cost_usd,
    token_spike,
)


def test_입력과_출력을_각각의_단가로_센다():
    """출력이 5배 비싸다. 입력만 세면 비용을 크게 낮잡는다."""
    runs = [{"input_tokens": 1_000_000, "output_tokens": 1_000_000}]

    assert month_cost_usd(runs, model="claude-opus-5-5") == 24.0   # 4 + 20


def test_단가가_문서와_같다():
    """2026-11-18 claude-api 문서: Opus 5.5 $4 / $20 per MTok.
    단가가 바뀌면 여기서 먼저 깨진다."""
    assert PRICES["claude-opus-5-5"] == (4.0, 20.0)


def test_값이_없는_실행은_0으로_세지_않고_건너뛴다():
    """배선 전 실행은 None이다. 0으로 세면 '안 썼다'가 되어 거짓 안심이다."""
    runs = [
        {"input_tokens": None, "output_tokens": None},
        {"input_tokens": 1_000_000, "output_tokens": 0},
    ]

    assert month_cost_usd(runs, model="claude-opus-5-5") == 4.0


def test_한쪽만_있는_실행도_건너뛴다():
    """출력이 비싼 쪽이다. 입력만 세고 출력을 0으로 두면 가장 큰 몫을 놓친다."""
    runs = [{"input_tokens": 1_000_000, "output_tokens": None}]

    assert month_cost_usd(runs, model="claude-opus-5-5") is None


def test_잰_실행이_하나도_없으면_모른다():
    """**원안은 0.0을 돌려줬다.** 그러면 "이번 달 $0 / 예산 $10"이 된다.
    2026-11-18 실측: runs 3행 모두 토큰이 비어 있다(배선 전). 지금 이 가드가
    말할 수 있는 것은 "모른다"뿐이다."""
    runs = [{"input_tokens": None, "output_tokens": None}]

    assert month_cost_usd(runs, model="claude-opus-5-5") is None
    assert month_cost_usd([], model="claude-opus-5-5") is None


def test_모르는_모델이면_분명하게_실패한다():
    """모델을 바꾸고 단가를 안 넣으면 KeyError 한 단어로 끝난다. 무엇을 할지 말한다."""
    with pytest.raises(KeyError, match="PRICES"):
        month_cost_usd([{"input_tokens": 1, "output_tokens": 1}], model="claude-x")


def test_표본이_적으면_급증을_판정하지_않는다():
    """이틀치로 '평소의 3배'를 판정하면 셋째 날마다 경고가 뜬다."""
    runs = [{"input_tokens": 1000}, {"input_tokens": 1000}]

    assert token_spike(runs, today_input=9999) is False


def test_중앙값의_3배를_넘으면_급증이다():
    runs = [{"input_tokens": 1000} for _ in range(10)]

    assert token_spike(runs, today_input=3001) is True
    assert token_spike(runs, today_input=2999) is False


def test_임계값들():
    assert BUDGET_WARN_RATIO == 0.8
    assert SPIKE_FACTOR == 3


# --- 새로 생긴 소스 실패 ---
#
# collect_warnings의 "고쳐야 할 소스"는 콘솔에만 찍힌다. Actions 로그는 아무도
# 매일 읽지 않으므로, 2026-11-18 우아한형제들 403(러너 IP에서만)이 침묵 가드가
# 잡을 30일 뒤까지 묻힐 뻔했다. 그대로 슬랙에 보내면 같은 실패가 매일 반복
# 알림이 된다 — 그래서 **어제는 없던 실패만** 알린다.

from pipeline.lib.guard import new_source_failures


def _err(source, kind="config", message="HTTP 403"):
    return {"source": source, "kind": kind, "message": message}


def test_직전_실행에_없던_설정_실패는_새_실패다():
    runs = [{"briefing_date": "2026-11-12", "errors": []}]

    found = new_source_failures([_err("우아한형제들")], runs, today=date(2026, 11, 18))

    assert found == [_err("우아한형제들")]


def test_직전_실행에도_있던_실패는_다시_알리지_않는다():
    runs = [{"briefing_date": "2026-11-18", "errors": [_err("우아한형제들")]}]

    assert new_source_failures([_err("우아한형제들")], runs, today=date(2026, 11, 19)) == []


def test_일시_실패는_알리지_않는다():
    """기다리면 되는 실패다 — 사람이 할 일이 없다(collect_warnings와 같은 기준)."""
    assert new_source_failures([_err("HN", kind="transient")], [], today=TODAY) == []


def test_주소_이전도_새로_생기면_알린다():
    found = new_source_failures([_err("토스", kind="moved", message="a → b")], [], today=TODAY)

    assert [f["kind"] for f in found] == ["moved"]


def test_직전_실행이_없으면_지금_실패가_전부_새것이다():
    assert len(new_source_failures([_err("a"), _err("b")], [], today=TODAY)) == 2


def test_가장_최근_실행일만_비교한다():
    """그제 실패했다가 어제 회복하고 오늘 다시 실패하면 새로 알린다 —
    어제 고쳐졌다고 생각했을 것이다."""
    runs = [
        {"briefing_date": "2026-11-16", "errors": [_err("토스")]},
        {"briefing_date": "2026-11-17", "errors": []},
    ]

    assert new_source_failures([_err("토스")], runs, today=date(2026, 11, 18)) == [_err("토스")]


def test_같은_날의_여러_행은_합쳐서_본다():
    """2026-11-12처럼 한 날짜에 행이 여럿일 수 있다(개발 중 --force 흔적)."""
    runs = [
        {"briefing_date": "2026-11-17", "errors": []},
        {"briefing_date": "2026-11-17", "errors": [_err("토스")]},
    ]

    assert new_source_failures([_err("토스")], runs, today=date(2026, 11, 18)) == []


def test_종류가_바뀌면_새_실패다():
    """주소 이전이던 소스가 아예 막히면(moved → config) 할 일이 달라진다."""
    runs = [{"briefing_date": "2026-11-17", "errors": [_err("토스", kind="moved")]}]

    assert len(new_source_failures([_err("토스")], runs, today=date(2026, 11, 18))) == 1


def test_오늘_행은_직전으로_치지_않는다():
    """--force로 같은 날 다시 돌리면 오늘 행이 이미 있다. 그건 '어제'가 아니다."""
    runs = [
        {"briefing_date": "2026-11-17", "errors": []},
        {"briefing_date": "2026-11-18", "errors": [_err("토스")]},
    ]

    assert len(new_source_failures([_err("토스")], runs, today=date(2026, 11, 18))) == 1
