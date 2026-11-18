"""워크플로(.github/workflows/daily.yml)가 코드와 어긋나지 않는지 본다.

어긋나면 아침 07:20에 처음 드러난다. 사람이 없는 시각이다.
"""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from pipeline.lib.timeutil import KST
from pipeline.report_failure import RUN_HOUR, RUN_MINUTE, RUN_WEEKDAYS

WORKFLOW = Path(".github/workflows/daily.yml")


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers(wf: dict) -> dict:
    # **PyYAML은 `on:`을 불리언 True로 읽는다**(YAML 1.1에서 on은 참이다).
    # wf["on"]으로 찾으면 KeyError가 난다.
    return wf.get("on") or wf[True]


def _cron_days(field: str) -> set[int]:
    """cron 요일 칸(0=일요일)을 집합으로. 이 워크플로가 쓰는 형식만 받는다."""
    if field == "*":
        return set(range(7))
    days: set[int] = set()
    for part in field.split(","):
        if "-" in part:
            a, b = part.split("-")
            days |= set(range(int(a), int(b) + 1))
        else:
            days.add(int(part))
    return {7 % 7 if d == 7 else d for d in days}


def test_cron이_실패_보고의_정기_실행_시각과_같다():
    """report_failure가 "다음 정기 실행"을 계산해 "다시 돌릴지"를 판단한다.
    cron만 바꾸고 그쪽을 잊으면 판단이 틀린다(Task 13)."""
    [schedule] = _triggers(_workflow())["schedule"]
    minute, hour, dom, month, dow = schedule["cron"].split()
    assert (dom, month) == ("*", "*")

    # 한 주를 돌며 cron이 발동하는 순간을 KST로 바꿔 모은다.
    fired = set()
    monday = datetime(2026, 11, 16, tzinfo=timezone.utc)
    for offset in range(7):
        day = monday + timedelta(days=offset)
        cron_dow = (day.weekday() + 1) % 7          # 파이썬 월=0 → cron 일=0
        if cron_dow in _cron_days(dow):
            moment = day.replace(hour=int(hour), minute=int(minute)).astimezone(KST)
            fired.add((moment.weekday(), moment.hour, moment.minute))

    assert fired == {(d, RUN_HOUR, RUN_MINUTE) for d in RUN_WEEKDAYS}


def test_코드가_요구하는_환경변수가_워크플로에_다_있다():
    """`require("X")`를 하나 더하고 Secret 등록을 잊으면 그날 아침 실행이 죽는다."""
    required = set()
    for path in Path("pipeline").rglob("*.py"):
        required |= set(re.findall(r'require\("([A-Z_]+)"\)', path.read_text(encoding="utf-8")))

    provided = set(_workflow()["jobs"]["briefing"]["env"])

    assert required, "require 호출을 하나도 못 찾았다 — 정규식이 틀렸다"
    assert required <= provided, f"워크플로에 없다: {sorted(required - provided)}"


def test_비밀은_secrets에서만_온다():
    """비밀을 평문으로 적으면 공개 리포에 그대로 올라간다."""
    env = _workflow()["jobs"]["briefing"]["env"]
    secret_like = {k for k in env if k.endswith(("_KEY", "_SECRET", "_SECRET_KEY")) or "WEBHOOK" in k}

    for key in secret_like:
        assert str(env[key]).startswith("${{ secrets."), f"{key}가 평문이다"


def test_토큰_권한은_읽기_전용이다():
    assert _workflow()["permissions"] == {"contents": "read"}


def test_의존성을_고정해서_설치한다():
    steps = _workflow()["jobs"]["briefing"]["steps"]
    install = next(s for s in steps if s.get("id") == "install")

    assert "-c constraints.txt" in install["run"]
    assert Path("constraints.txt").exists()


def test_실패_보고가_모든_단계를_안다():
    """단계를 더하고 FAILED_STEP 식에 안 넣으면 그 단계의 실패가 엉뚱한 이름으로 보고된다."""
    steps = _workflow()["jobs"]["briefing"]["steps"]
    ids = [s["id"] for s in steps if "id" in s]
    report = next(s for s in steps if s.get("if") == "failure()")
    expression = report["env"]["FAILED_STEP"]

    for step_id in ids:
        assert f"steps.{step_id}.outcome" in expression, f"{step_id}가 FAILED_STEP에 없다"
    assert report["run"] == "python -m pipeline.report_failure"


def test_실패_훈련은_손으로_켤_때만_수집_전에_돈다():
    """훈련이 예약 실행에서 돌면 매일 아침이 실패한다. 수집 뒤에 있으면
    API를 부르고 기록을 남긴 뒤에 실패한다."""
    wf = _workflow()
    steps = wf["jobs"]["briefing"]["steps"]
    ids = [s.get("id") for s in steps]
    drill = steps[ids.index("drill")]

    assert drill["if"] == "inputs.drill_failure"
    assert ids.index("drill") < ids.index("collect")
    assert _triggers(wf)["workflow_dispatch"]["inputs"]["drill_failure"]["default"] is False
