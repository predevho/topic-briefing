"""Supabase 연결과 권한을 1회 확인한다. 운영 파이프라인에 포함되지 않는다.

실행: python scripts/smoke_supabase.py

**스스로 정리한다.** runs에 테스트 행을 넣고 읽어본 뒤 지운다.
남겨두면 last_sent_at()이 그것을 읽어서 첫 실제 수집의 윈도우가 거의 0이
되고, 아무것도 수집하지 않는다.
"""

from datetime import datetime, timedelta, timezone

from pipeline.lib.secrets import require
from pipeline.lib.store import SupabaseStore

# 테스트 행을 찾아 지우기 위한 표식. source_counts에 넣는다.
MARKER = "__smoke_test__"

# 실제 키 대신 이 문장을 키 자리에 넣는다. 예외 메시지에 이게 나타나면
# 실제 secret 키도 같은 자리에 나타난다는 뜻이다.
SENTINEL_KEY = "sb_secret_sentinel_must_not_appear_in_error_messages"


def check_key_does_not_leak() -> bool:
    """잘못된 키로 호출해 예외 메시지에 키가 들어가는지 확인한다.

    왜 확인해야 하나: 리포지토리가 퍼블릭이면 **Actions 로그도 누구나
    볼 수 있다.** SupabaseStore가 올리는 예외에 Authorization 헤더나
    키가 섞여 있으면 secret 키가 그 로그에 남고, 그러면 DB 전체가 열린다.

    실제 키를 쓰지 않으므로 이 점검 자체가 키를 노출하지 않는다.
    """
    bad = SupabaseStore(require("SUPABASE_URL"), SENTINEL_KEY)

    try:
        bad.last_sent_at()
    except Exception as error:  # noqa: BLE001 — 메시지를 보는 것이 목적이다
        message = f"{type(error).__name__}: {error}"
        print(f"   예외: {message[:200]}")
        if SENTINEL_KEY in message:
            print("   ★ 키가 예외 메시지에 들어간다.")
            print("     SupabaseStore의 각 메서드를 try/except로 감싸고,")
            print("     키를 제거한 메시지로 다시 올려야 한다.")
            return False
        print("   → 키는 새지 않았다.")
        return True

    print("   ★ 잘못된 키인데 호출이 성공했다. 키 검증 경로를 확인한다.")
    return False


def main() -> None:
    url = require("SUPABASE_URL")
    store = SupabaseStore(url, require("SUPABASE_SECRET_KEY"))
    now = datetime.now(timezone.utc)

    print("1) 마지막 발송 시각 조회...")
    before = store.last_sent_at()
    print(f"   → {before}  (최초 실행이면 None)")

    print("2) 실행 이력 쓰기...")
    store.record_run(
        window_start=now - timedelta(hours=24),
        window_end=now,
        status="sent",
        sent_at=now,
        collected_count=0,
        considered_count=0,
        max_score=None,
        published_count=0,
        source_counts={MARKER: 0},
        input_tokens=None,
        errors=[],
    )
    after = store.last_sent_at()
    print(f"   → 기록 후 조회: {after}")
    round_trip = after is not None and abs((after - now).total_seconds()) < 5
    print(f"   → 왕복 일치: {'✓' if round_trip else '★ 쓴 값과 읽은 값이 다르다'}")

    print("3) 발행 URL 조회...")
    print(f"   → {store.known_urls(['https://example.com/none'])}  (빈 집합이 정상)")

    print("4) 최근 헤드라인 조회...")
    print(f"   → {len(store.recent_headlines(days=14))}건")

    print("5) 테스트 행 정리...")
    # SupabaseStore에 delete를 두지 않는다 — 운영에서 쓰지 않는 기능이다.
    # 스크립트이므로 클라이언트를 직접 쓴다.
    from supabase import create_client

    db = create_client(url, require("SUPABASE_SECRET_KEY"))
    removed = (
        db.table("runs")
        .delete()
        .contains("source_counts", {MARKER: 0})
        .execute()
        .data
    )
    print(f"   → {len(removed)}행 삭제")
    restored = store.last_sent_at()
    print(f"   → 정리 후 조회: {restored}  (1번과 같아야 한다: {before})")
    if restored != before:
        print("   ★ 정리가 덜 됐다. runs를 직접 확인한다:")
        print(f"     delete from public.runs where source_counts ? '{MARKER}';")
        raise SystemExit(1)

    print("6) 예외 메시지에 비밀값이 새는지...")
    if not check_key_does_not_leak():
        raise SystemExit(1)

    print()
    print("성공. 연결·쓰기·읽기·정리가 모두 동작하고 키가 새지 않는다.")


if __name__ == "__main__":
    main()
