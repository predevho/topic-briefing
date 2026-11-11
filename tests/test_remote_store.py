"""가짜 구현이 인터페이스를 만족하는지 확인한다.

실제 SupabaseStore는 단위 테스트하지 않는다. 대부분이 DB 호출 통과이고,
모킹하면 '내가 쓴 모킹이 맞는가'만 검증하게 된다. 실제 동작은
scripts/smoke_supabase.py로 1회 확인한다.
"""

from datetime import datetime, timezone

from pipeline.lib.store import RemoteStore
from tests.fakes import FakeRemoteStore


def test_가짜_구현이_인터페이스를_만족한다():
    """Protocol은 런타임 검사가 아니므로 명시적으로 확인한다."""
    fake: RemoteStore = FakeRemoteStore()
    assert fake is not None


def test_발송_이력이_없으면_None을_돌려준다():
    fake = FakeRemoteStore()
    assert fake.last_sent_at() is None


def test_기록한_실행의_시각을_돌려준다():
    fake = FakeRemoteStore()
    sent = datetime(2026, 11, 10, 22, 20, tzinfo=timezone.utc)

    fake.record_run(
        window_start=datetime(2026, 11, 9, 22, 20, tzinfo=timezone.utc),
        window_end=sent,
        status="sent",
        sent_at=sent,
        collected_count=42,
        considered_count=10,
        max_score=94,
        published_count=3,
        source_counts={"s": 5},
        input_tokens=12000,
        errors=[],
    )

    assert fake.last_sent_at() == sent


def test_실패한_실행은_마지막_발송으로_세지_않는다():
    """세면 원인을 고친 뒤 재실행이 "이미 보냄"으로 막힌다."""
    fake = FakeRemoteStore()

    fake.record_run(
        window_start=datetime(2026, 11, 9, 22, 20, tzinfo=timezone.utc),
        window_end=datetime(2026, 11, 10, 22, 20, tzinfo=timezone.utc),
        status="failed",
        sent_at=None,
        collected_count=42,
        considered_count=10,
        max_score=94,
        published_count=0,
        source_counts={"s": 5},
        input_tokens=None,
        errors=[{"source": "sender:kakao", "kind": "config", "message": "HTTP 404"}],
    )

    assert fake.last_sent_at() is None
    assert len(fake.runs) == 1          # 기록은 남는다


def test_이미_발행한_URL을_알려준다():
    fake = FakeRemoteStore(known={"https://e.com/a"})
    found = fake.known_urls(["https://e.com/a", "https://e.com/b"])
    assert found == {"https://e.com/a"}


def test_최근_헤드라인을_돌려준다():
    fake = FakeRemoteStore(headlines=["어제 그 글", "그제 그 글"])
    assert fake.recent_headlines(days=14) == ["어제 그 글", "그제 그 글"]
