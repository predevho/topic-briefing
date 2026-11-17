"""시드에서 소스별 **마지막 글 날짜**를 뽑아 config/seed_last_seen.json에 쓴다.

왜 필요한가: 소스 침묵 가드는 runs.source_counts로 "마지막으로 글이 보인
날"을 찾는다. 그런데 runs는 2026-11-12부터만 있다. 그 전부터 조용하던 소스는
runs에서 **영원히 못 본 것(None)**이 되어 절대 경고하지 않는다. 가드가 잡아야
할 바로 그 경우다.

2026-11-17 실측: 11/12 실행에서 45개 중 16개가 0건이었고, 그중
하이퍼커넥트는 시드상 마지막 글이 209일 전이다(monthly, 기준 200일).

시드(data/_seed/raw.json)는 400일 윈도우로 피드 전체를 받은 것이라 각 소스의
진짜 마지막 글을 안다. 그러나 data/는 gitignore라 GitHub Actions에 없다.
그래서 **필요한 45줄만** 뽑아 config/에 커밋한다.

한 번 돌리면 된다. 시드를 다시 받았을 때만 다시 돌린다.

실행: .venv/bin/python scripts/seed_last_seen.py
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pipeline.lib.timeutil import KST

SEED = Path("data/_seed/raw.json")
OUT = Path("config/seed_last_seen.json")


def main() -> None:
    bundle = json.loads(SEED.read_text(encoding="utf-8"))

    # 날짜는 KST로 센다. 가드의 today가 briefing_date(KST)이므로 단위를 맞춘다.
    seed_date = datetime.fromisoformat(bundle["window_end"]).astimezone(KST).date()

    last: dict[str, str] = {}
    for item in bundle["items"]:
        day = datetime.fromisoformat(item["published"]).astimezone(KST).date().isoformat()
        if item["source"] not in last or day > last[item["source"]]:
            last[item["source"]] = day

    OUT.write_text(
        json.dumps(
            {
                "_note": (
                    "소스별 마지막 글 날짜(KST). scripts/seed_last_seen.py가 "
                    "data/_seed/raw.json에서 만든다. 손으로 고치지 않는다. "
                    "침묵 가드가 runs에서 한 번도 못 본 소스의 출발점으로 쓴다."
                ),
                "seed_date": seed_date.isoformat(),
                "last_seen": dict(sorted(last.items())),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{OUT}: 소스 {len(last)}개, 시드 날짜 {seed_date}")


if __name__ == "__main__":
    main()
