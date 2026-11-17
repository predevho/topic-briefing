"""조용히 실패하는 것들을 잡는다.

브리핑이 오지 않으면 "오늘 뉴스가 없었나보다"로 착각하게 되고, 그것이
2주 지속되면 시스템이 죽은 것을 모른다. 더 나쁜 것은 브리핑이 **정상적으로
오면서** 내용만 조금씩 빈약해지는 경우다 — 아무 신호가 없다. 소스 하나가
조용히 죽는 것이 바로 그렇다.

가치 순서는 **소스 침묵 > 토큰 만료 > 크레딧**이다(스펙 8.4).
"""

from __future__ import annotations

import json
from datetime import date
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
