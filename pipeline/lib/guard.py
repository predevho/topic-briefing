"""조용히 실패하는 것들을 잡는다.

브리핑이 오지 않으면 "오늘 뉴스가 없었나보다"로 착각하게 되고, 그것이
2주 지속되면 시스템이 죽은 것을 모른다. 더 나쁜 것은 브리핑이 **정상적으로
오면서** 내용만 조금씩 빈약해지는 경우다 — 아무 신호가 없다. 소스 하나가
조용히 죽는 것이 바로 그렇다.

가치 순서는 **소스 침묵 > 토큰 만료 > 크레딧**이다(스펙 8.4).
"""

from __future__ import annotations

import json
import statistics
from datetime import date, datetime
from pathlib import Path

from pipeline.lib.config import Source

# --- 소스 침묵 ---
#
# 지표는 "N일 연속 0건"이 아니라 **마지막으로 글이 보인 날로부터 경과일**이다.
# 0건은 수집 윈도우(최대 96시간) 기준이라 주간 소스는 7일 중 5일이 0건이고,
# "연속" 카운트는 소스의 실제 상태와 어긋난다.

# 등급별 임계값(일). 소스의 **관측된 최대공백**으로 등급을 나눴다
# (시드 2026-11-12, 400일 윈도우 측정 — 계획 3 Task 9).
QUIET_THRESHOLDS: dict[str, int | None] = {
    "fast": 30,       # 최대공백 ≤ 16일
    "weekly": 90,     # 17~45일
    "monthly": 200,   # 46~130일
    "none": None,     # 131일+ 또는 표본 3건 미만 — 가드에서 뺀다
}

DEFAULT_SEED_PATH = Path("config/seed_last_seen.json")


def load_seed_last_seen(path: Path | None = None) -> dict[str, date]:
    """시드에서 뽑은 소스별 마지막 글 날짜. 파일이 없으면 빈 dict.

    파일이 없다고 멈추지 않는다 — runs만으로도 가드는 돈다. 다만 시드 이전부터
    조용하던 소스를 못 잡을 뿐이다(scripts/seed_last_seen.py 머리말).
    """
    path = path or DEFAULT_SEED_PATH
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {name: date.fromisoformat(day) for name, day in data["last_seen"].items()}


def days_since_seen(
    runs: list[dict],
    source: str,
    *,
    today: date,
    seed: dict[str, date] | None = None,
) -> int | None:
    """그 소스에서 마지막으로 글이 온 날로부터 며칠인가.

    "마지막으로 본 날"은 **runs에서 양수였던 날과 시드의 마지막 글 날짜 중
    늦은 쪽**이다.

    - runs의 순서에 기대지 않는다. 양수인 날 중 가장 늦은 날을 쓴다 —
      질의가 정렬을 빠뜨려도 답이 같다.
    - 0인 행은 건너뛴다. 0은 "이번 윈도우에 못 봤다"이지 "죽었다"가 아니고,
      빈 테스트 행(2026-11-12에 2행)이 침묵으로 보여서도 안 된다.
    - 시드를 더하는 이유: runs는 2026-11-12부터다. 그 전부터 조용하던 소스는
      runs만으로는 영원히 None이 되어 **절대 경고하지 않는다.**

    둘 다 없으면 None — 새로 넣은 소스다. **"오래 조용하다"와 "처음부터
    없었다"는 다른 문제다.** 새 소스를 죽었다고 경고하면 그게 오탐이다.

    runs는 가장 높은 임계값(200일)보다 길게 받아야 한다. 짧으면 그보다 오래된
    양수를 못 보고 시드 날짜로 물러서서 경과일이 부풀려진다.
    """
    seen = [
        date.fromisoformat(run["briefing_date"])
        for run in runs
        if (run.get("source_counts") or {}).get(source, 0) > 0
    ]
    if seed and source in seed:
        seen.append(seed[source])

    if not seen:
        return None
    return (today - max(seen)).days


def silent_sources(
    sources: list[Source],
    runs: list[dict],
    *,
    today: date,
    seed: dict[str, date] | None = None,
) -> list[tuple[str, int, int]]:
    """임계값을 넘긴 소스를 (이름, 경과일, 임계값)으로 돌려준다.

    임계값을 함께 주는 이유: "토스가 조용하다"보다 "토스 45일째 (기준
    30일)"가 조치로 이어진다. 기준을 올릴지 소스를 끌지 판단할 수 있다.
    """
    found = []
    for source in sources:
        limit = QUIET_THRESHOLDS[source.quiet_tier]
        if limit is None:
            continue
        gap = days_since_seen(runs, source.name, today=today, seed=seed)
        if gap is not None and gap >= limit:
            found.append((source.name, gap, limit))
    return found


# --- 토큰 만료 ---
#
# 카카오 refresh_token은 60일이다(2026-11-17 실측: refresh_token_expires_in
# 5,184,000초). 만료가 1개월 미만이면 갱신 때 새 토큰이 오고, 저장하면 수명이
# 다시 60일이 된다. 그래서 **정상이면 남은 일수가 30일 아래로 거의 내려가지
# 않는다.** 이 경고가 뜨면 회전 저장이 2주 넘게 실패했거나 파이프라인이 한 달
# 넘게 멈춘 것이다.

# 재인증은 브라우저에서 사람이 해야 한다(scripts/kakao_auth.py).
# 2주면 주말을 두 번 지나므로 바쁜 주에도 처리할 시간이 있다.
TOKEN_WARN_DAYS = 14


def token_expiring(expires_at: datetime, *, now: datetime) -> int | None:
    """만료까지 남은 일수. 여유가 있으면 None.

    음수를 그대로 돌려준다 — "3일 지났다"가 "0일 남았다"보다 정확하고,
    이미 끊긴 상태와 곧 끊길 상태는 다른 조치를 부른다.

    `.days`는 내림이다 — 13일 23시간은 13일. 남은 시간을 짧게 말하는 쪽이라
    경고에는 맞는 방향이다.
    """
    days = (expires_at - now).days
    return days if days <= TOKEN_WARN_DAYS else None


# --- 크레딧 ---
#
# **Anthropic은 잔여 크레딧을 알려주지 않는다.** Usage and Cost Analytics의
# /cost는 "할인 후, 크레딧 적용 전" 금액이고 Admin API 키와 4~24시간 지연이
# 따른다. 그래서 우리 사용량을 누적해 내가 정한 예산과 비교한다(설계 0.1).

# 모델별 단가 (USD per 1M tokens): 입력, 출력.
# 2026-11-18 claude-api 문서로 확인. **정가 기준이라 실제 청구액과 다르다** —
# 할인과 크레딧 적용 전이다. 목적은 정확한 금액이 아니라 조기 소진 감지다.
# 사고(thinking) 토큰은 출력으로 과금되고 usage.output_tokens에 이미 들어 있다.
# 캐시는 쓰지 않는다(쓰면 캐시 쓰기·읽기 단가가 따로 필요하다).
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
}

BUDGET_WARN_RATIO = 0.8    # 월 예산의 80%를 넘으면 알린다
SPIKE_FACTOR = 3           # 평소의 3배
SPIKE_MIN_SAMPLES = 5      # 이보다 적으면 판정하지 않는다


def month_cost_usd(runs: list[dict], *, model: str) -> float | None:
    """그 달 실행들이 쓴 비용(정가 기준). 잰 실행이 하나도 없으면 None.

    입력·출력 중 하나라도 None인 실행은 **건너뛴다.** 0으로 세면 "안 썼다"가
    되어 비용을 낮잡는다 — 특히 출력이 5배 비싸서 출력을 0으로 두면 가장 큰
    몫을 놓친다.

    잰 실행이 없으면 0.0이 아니라 None이다. 0.0이면 "이번 달 $0"이라는
    거짓 안심이 된다(2026-11-18: runs 3행 모두 배선 전이라 비어 있다).

    어느 달의 runs를 넘길지는 호출부가 정한다(KST 기준 그 달).
    """
    if model not in PRICES:
        raise KeyError(
            f"{model}의 단가가 없다. pipeline/lib/guard.py의 PRICES에 "
            f"(입력, 출력) USD/MTok을 더한다."
        )
    price_in, price_out = PRICES[model]

    measured = [
        run for run in runs
        if run.get("input_tokens") is not None and run.get("output_tokens") is not None
    ]
    if not measured:
        return None

    total = sum(
        run["input_tokens"] / 1_000_000 * price_in
        + run["output_tokens"] / 1_000_000 * price_out
        for run in measured
    )
    return round(total, 4)


def token_spike(runs: list[dict], *, today_input: int) -> bool:
    """오늘 입력 토큰이 평소(중앙값)의 3배를 넘는가.

    피드 하나가 갑자기 10배를 쏟아내는 것 같은 **당일 이상**을 잡는다.
    예산 비율은 느린 누수를 잡고, 이쪽이 사고를 잡는다.

    표본이 적으면 판정하지 않는다 — 이틀치로 중앙값을 내면 셋째 날마다
    경고가 뜬다. 중앙값인 이유: 평균은 그 사고 하루에 끌려 올라간다.
    """
    history = [r["input_tokens"] for r in runs if r.get("input_tokens")]
    if len(history) < SPIKE_MIN_SAMPLES:
        return False
    return today_input > statistics.median(history) * SPIKE_FACTOR


# --- 새로 생긴 소스 실패 ---
#
# collect_warnings의 "고쳐야 할 소스"·"주소 이전"은 콘솔에만 찍힌다. Actions
# 로그는 아무도 매일 읽지 않는다 — 2026-11-18 우아한형제들 403(러너 IP에서만)이
# 침묵 가드가 잡을 30일 뒤까지 묻힐 뻔했다. 그대로 슬랙에 보내면 같은 실패가
# 매일 반복 알림이 되므로 **직전 실행일에 없던 실패만** 알린다.

# 사람이 고쳐야 하는 종류만. transient는 기다리면 된다 — 할 일이 없다.
ACTIONABLE_KINDS = frozenset({"config", "moved"})


def new_source_failures(
    today_errors: list[dict], runs: list[dict], *, today: date
) -> list[dict]:
    """오늘 수집 오류 중 **직전 실행일에 없던** (소스, 종류)를 돌려준다.

    - 직전 실행일은 오늘보다 앞선 가장 늦은 briefing_date다. 그날 행이 여럿이면
      합쳐서 본다(2026-11-12처럼 개발 중 --force 흔적이 있다).
    - 오늘 행은 직전으로 치지 않는다 — --force 재실행이 그것과 비교하면 안 된다.
    - 그제 실패하고 어제 회복했다가 오늘 다시 실패하면 새로 알린다. 어제
      고쳐졌다고 생각했을 것이다.
    - 종류가 바뀌면(moved → config) 새 실패다. 할 일이 달라진다.

    계속되는 실패는 첫날 한 번만 알린다. 그 뒤로도 막혀 있으면 침묵 가드가
    등급 기준일(fast 30일)에 다시 알린다.
    """
    earlier = [r for r in runs if r["briefing_date"] < today.isoformat()]
    if earlier:
        last_day = max(r["briefing_date"] for r in earlier)
        seen = {
            (e.get("source"), e.get("kind"))
            for r in earlier if r["briefing_date"] == last_day
            for e in (r.get("errors") or [])
        }
    else:
        seen = set()

    return [
        e for e in today_errors
        if e["kind"] in ACTIONABLE_KINDS and (e["source"], e["kind"]) not in seen
    ]
