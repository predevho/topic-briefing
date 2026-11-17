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
