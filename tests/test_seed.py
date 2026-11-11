from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline.lib.config import Source
from pipeline.lib.http import FetchResult
from pipeline.lib.store import LocalStore
from pipeline.seed import (
    IGNORE_HISTORY,
    SEED_DIR,
    ensure_writable,
    run_seed,
    seed_window,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _source() -> Source:
    return Source(name="s", url="https://e.com/r", kind="rss", weight=1.0, lang="ko")


def _fetch(filename: str = "feed_two_items.xml"):
    data = (FIXTURES / filename).read_bytes()

    def fetch(url: str) -> FetchResult:
        # collect는 FetchResult를 기대한다. bytes를 그대로 돌려주면
        # result.moved_from에서 AttributeError가 난다.
        return FetchResult(content=data, final_url=url, moved_from=None)

    return fetch


def _store(tmp_path: Path) -> LocalStore:
    return LocalStore(date=SEED_DIR, root=tmp_path)


# --- 윈도우 ---

def test_시드_윈도우가_아주_넓다():
    """피드가 주는 전부를 받으려면 윈도우가 과거를 충분히 덮어야 한다."""
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    start, end = seed_window(now=now)

    assert end == now
    assert (end - start).days >= 365


def test_시드는_별도_디렉터리를_쓴다():
    """운영 날짜 디렉터리와 섞이면 일반 실행이 시드를 덮어쓴다."""
    assert SEED_DIR == "_seed"


def test_오래된_항목도_수집된다(tmp_path):
    """fixture의 2025년 글이 들어와야 한다 — 운영 수집에서는 걸러진 항목."""
    bundle = run_seed(
        sources=[_source()],
        now=datetime(2026, 11, 10, 22, 20, tzinfo=timezone.utc),
        fetch=_fetch(),
        store=_store(tmp_path),
    )

    assert len(bundle.items) == 2


def test_발행_이력을_보지_않는다():
    """운영 수집은 이미 발행한 URL을 뺀다. 시드는 튜닝 재료이므로
    발행 여부와 무관하게 전부 받아야 한다.
    """
    assert IGNORE_HISTORY(["https://a.com/1", "https://b.com/2"]) == set()


# --- 덮어쓰기 방지 ---

def test_이미_있는_시드는_덮어쓰지_않는다(tmp_path):
    """이게 이 태스크에서 가장 위험한 지점이다.

    한 달 뒤에 무심코 다시 돌리면, 그때 피드는 이미 과거를 버렸으므로
    **더 적은 데이터로 원본을 덮어쓴다.** 되돌릴 수 없는 손실이고
    증상도 없다 — 파일은 그대로 있고 안에 든 것만 줄어든다.
    """
    store = _store(tmp_path)
    run_seed(sources=[_source()], now=datetime(2026, 11, 10, tzinfo=timezone.utc),
             fetch=_fetch(), store=store)

    with pytest.raises(SystemExit, match="이미 있다"):
        run_seed(sources=[_source()], now=datetime(2026, 12, 10, tzinfo=timezone.utc),
                 fetch=_fetch(), store=store)


def test_force를_주면_덮어쓴다(tmp_path):
    """막아 두더라도 빠져나갈 길은 있어야 한다. 다만 기본값이 아니다."""
    store = _store(tmp_path)
    run_seed(sources=[_source()], now=datetime(2026, 11, 10, tzinfo=timezone.utc),
             fetch=_fetch(), store=store)

    bundle = run_seed(sources=[_source()], now=datetime(2026, 12, 10, tzinfo=timezone.utc),
                      fetch=_fetch(), store=store, force=True)
    assert len(bundle.items) == 2


def test_시드가_없으면_그냥_쓴다(tmp_path):
    ensure_writable(_store(tmp_path), force=False)      # 예외가 나지 않는다


def test_거부_메시지가_force를_알려준다(tmp_path):
    """막기만 하고 빠져나갈 방법을 안 알려주면 사용자가 파일을 손으로 지운다."""
    store = _store(tmp_path)
    run_seed(sources=[_source()], now=datetime(2026, 11, 10, tzinfo=timezone.utc),
             fetch=_fetch(), store=store)

    with pytest.raises(SystemExit, match="--force"):
        ensure_writable(store, force=False)


# --- 저장 ---

def test_시드를_파일로_쓴다(tmp_path):
    store = _store(tmp_path)
    run_seed(sources=[_source()], now=datetime(2026, 11, 10, tzinfo=timezone.utc),
             fetch=_fetch(), store=store)

    assert (tmp_path / SEED_DIR / "raw.json").exists()


def test_항목이_없어도_파일은_쓴다(tmp_path):
    """0건이어도 "언제 시도했는지"는 남아야 한다. 다만 다음 실행이
    이걸 보고 거부하므로, 0건이면 사용자가 force로 다시 돌린다.
    """
    store = _store(tmp_path)
    bundle = run_seed(sources=[_source()],
                      now=datetime(2026, 11, 10, tzinfo=timezone.utc),
                      fetch=_fetch("feed_empty.xml"), store=store)

    assert bundle.items == []
    assert store.exists("raw")
