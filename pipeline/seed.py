"""시드 수집 (1회성): 각 소스가 제공하는 전체 항목을 긁어 저장한다.

운영 수집과 다른 점은 둘뿐이다 — 윈도우가 넓고, 발행 이력을 보지 않는다.
수집 로직은 collect를 그대로 재사용한다.

실행: python -m pipeline.seed

이 데이터는 선별 프롬프트 튜닝(pipeline.evaluate)의 재료다. 대부분의 RSS는
최근 10~50건만 제공하므로, **지금 긁지 않으면 다시 얻을 수 없다.**

같은 이유로 이 모듈은 **이미 있는 시드를 덮어쓰지 않는다.** 한 달 뒤에
무심코 다시 돌리면 그때 피드는 이미 과거를 버렸으므로 더 적은 데이터로
원본을 덮어쓴다. 파일은 그대로 있고 안에 든 것만 줄어드니 증상도 없다.
"""

import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from pipeline.collect import FetchFn, SleepFn, collect
from pipeline.lib.config import Source, load_sources
from pipeline.lib.http import fetch as http_fetch
from pipeline.lib.store import LocalStore
from pipeline.models import RawBundle

# 운영 날짜 디렉터리(2026-11-10)와 섞이지 않게 별도 이름을 쓴다.
SEED_DIR = "_seed"

# 피드가 주는 전부를 받기 위한 넉넉한 과거 범위.
#
# 더 넓힐 이유가 없다. 되돌릴 수 없는 것은 "오래된 글"이 아니라 **피드의
# 잘림**이다 — 10건만 주는 피드는 내일 11번째를 버린다. 400일은 어떤 피드가
# 담고 있는 범위보다 넓다. 반대로 과도하게 넓히면(10년) 2019년 글이 튜닝
# 표본에 섞여 들어와, 지금 들어올 글을 대표하지 못하는 재료가 된다.
SEED_LOOKBACK_DAYS = 400


def IGNORE_HISTORY(urls: list[str]) -> set[str]:  # noqa: N802 — 상수처럼 쓰는 주입값
    """시드는 발행 이력을 보지 않는다.

    운영 수집은 이미 발행한 URL을 뺀다(중복 발송 방지). 시드는 튜닝
    재료이므로 발행 여부와 무관하게 전부 받아야 한다.
    """
    return set()


def seed_window(*, now: datetime) -> tuple[datetime, datetime]:
    return now - timedelta(days=SEED_LOOKBACK_DAYS), now


def ensure_writable(store: LocalStore, *, force: bool) -> None:
    """이미 시드가 있으면 거부한다.

    막기만 하고 빠져나갈 방법을 알려주지 않으면 사용자가 파일을 손으로
    지운다. 그래서 메시지에 `--force`를 적는다.
    """
    if store.exists("raw") and not force:
        raise SystemExit(
            "시드가 이미 있다. 덮어쓰지 않는다.\n"
            f"  {SEED_DIR}/raw.json\n"
            "\n"
            "지금 다시 받으면 피드가 그동안 버린 과거가 빠진 채로 원본을\n"
            "덮어쓴다. 파일은 그대로 있고 안에 든 것만 줄어들어 알아차릴\n"
            "수도 없다.\n"
            "\n"
            "정말 다시 받아야 하면 기존 파일을 먼저 다른 이름으로 복사하고\n"
            "`python -m pipeline.seed --force`로 실행한다."
        )


def run_seed(
    *,
    sources: list[Source],
    now: datetime,
    store: LocalStore,
    fetch: FetchFn = http_fetch,
    known_urls: Callable[[list[str]], set[str]] = IGNORE_HISTORY,
    sleep: SleepFn = time.sleep,
    force: bool = False,
) -> RawBundle:
    """시드를 수집해 저장한다. 저장 전에 덮어쓰기를 막는다."""
    ensure_writable(store, force=force)

    window_start, window_end = seed_window(now=now)
    bundle = collect(
        sources=sources,
        window_start=window_start,
        window_end=window_end,
        fetch=fetch,
        known_urls=known_urls,
        sleep=sleep,
    )
    store.write("raw", bundle)
    return bundle


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    force = "--force" in args

    store = LocalStore(date=SEED_DIR)
    bundle = run_seed(
        sources=load_sources(),
        now=datetime.now(timezone.utc),
        store=store,
        force=force,
    )

    print(f"시드 수집 {len(bundle.items)}건 → {SEED_DIR}/raw.json")
    print(f"  윈도우: {bundle.window_start} ~ {bundle.window_end}")
    for name, count in sorted(bundle.source_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {count:4d}건  {name}")

    marks = {"config": "설정", "transient": "일시", "moved": "이전"}
    for error in bundle.errors:
        print(f"  [{marks[error.kind]}] {error.source}: {error.message}")

    print()
    print("이 파일은 선별 프롬프트 튜닝에 쓴다. 지우지 않는다.")
    print("다시 만들 수 없으므로 저장소 밖에 복사해 둔다.")


if __name__ == "__main__":
    main()
