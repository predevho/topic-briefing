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
        briefing_date="2026-11-11",
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
        output_tokens=None,
        errors=[],
    )

    assert fake.last_sent_at() == sent


def test_실패한_실행은_마지막_발송으로_세지_않는다():
    """세면 원인을 고친 뒤 재실행이 "이미 보냄"으로 막힌다."""
    fake = FakeRemoteStore()

    fake.record_run(
        briefing_date="2026-11-11",
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
        output_tokens=None,
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


def test_실행_이력에_브리핑_날짜를_남긴다():
    """0건인 날은 articles 행이 없으므로 runs가 그 날짜의 유일한 기록이다.

    날짜 컬럼이 없으면 페이지가 "조용한 날"과 "파이프라인이 안 돈 날"을
    구별할 수 없다. window_end를 KST로 변환해서 추측할 수는 있지만,
    브라우저 질의에 타임존 변환을 넣으면 인덱스를 못 타고 경계에서
    조용히 틀린다 (요구사항 D8).
    """
    fake = FakeRemoteStore()

    fake.record_run(
        briefing_date="2026-11-13",
        window_start=datetime(2026, 11, 12, 22, 20, tzinfo=timezone.utc),
        window_end=datetime(2026, 11, 13, 22, 20, tzinfo=timezone.utc),
        status="sent",
        sent_at=datetime(2026, 11, 13, 22, 20, tzinfo=timezone.utc),
        collected_count=240,
        considered_count=10,
        max_score=52,          # 기준 60점에 못 미친 날
        published_count=0,
        source_counts={"토스_기술블로그": 3},
        input_tokens=42135,
        output_tokens=None,
        errors=[],
    )

    assert fake.runs[0]["briefing_date"] == "2026-11-13"


def test_실행_이력에_출력_토큰도_남긴다():
    """크레딧 가드가 비용을 계산하려면 둘 다 필요하다.

    출력이 5배 비싸다 — opus-5-5 기준 입력 $4 / 출력 $20 per MTok.
    입력만 세면 비용을 크게 낮잡는다.
    """
    fake = FakeRemoteStore()

    fake.record_run(
        briefing_date="2026-11-17",
        window_start=datetime(2026, 11, 16, 22, 20, tzinfo=timezone.utc),
        window_end=datetime(2026, 11, 17, 22, 20, tzinfo=timezone.utc),
        status="sent",
        sent_at=datetime(2026, 11, 17, 22, 20, tzinfo=timezone.utc),
        collected_count=240,
        considered_count=10,
        max_score=100,
        published_count=7,
        source_counts={"토스_기술블로그": 3},
        input_tokens=50135,
        output_tokens=4220,
        errors=[],
    )

    assert fake.runs[0]["input_tokens"] == 50135
    assert fake.runs[0]["output_tokens"] == 4220


def test_기사_행에_순번을_1부터_매긴다():
    """카톡의 "3."과 페이지의 "3."이 같은 글이어야 한다.

    카톡은 summaries 순서로 번호를 매긴다. 페이지가 점수로 다시 정렬하면
    동점(2026-11-12에 100점 3건, 98점 3건) 사이 순서가 어긋난다. 그래서
    파이프라인이 매긴 순서를 그대로 저장한다.

    SupabaseStore는 모킹하지 않는다(파일 머리말). 행을 만드는 부분만 떼어
    순수 함수로 확인한다.
    """
    from pipeline.lib.store import article_rows
    from tests.test_sender import _summary

    # 같은 점수 셋 — 순서를 점수로는 정할 수 없는 경우다.
    summaries = [_summary(0), _summary(1), _summary(2)]

    rows = article_rows(briefing_date="2026-11-12", summaries=summaries)

    assert [row["position"] for row in rows] == [1, 2, 3]
    # 순번이 summaries 순서를 따른다 — 점수가 같아도.
    assert [row["url"] for row in rows] == [
        "https://toss.tech/a/0",
        "https://toss.tech/a/1",
        "https://toss.tech/a/2",
    ]
    assert all(row["briefing_date"] == "2026-11-12" for row in rows)
