"""카카오 발송을 **실제 운영 경로로** 한 번 확인한다.

계획 3 Task 6. 2026-11-17에 두 번 막히고 배운 것이 여기 들어간다.

고정 문구를 보내지 않는다. `pipeline.lib.kakao.access_token`과
`pipeline.lib.sender.KakaoSender`를 그대로 쓴다 — 매일 07:20에 돌 코드와
같은 경로여야 검증이 뜻이 있다. 스크립트가 따로 httpx를 부르면 "스크립트는
되는데 파이프라인은 안 되는" 상태를 못 잡는다.

## 두 가지 모드

    .venv/bin/python -u scripts/kakao_send_test.py
        Supabase의 최신 브리핑으로 보낸다.

    .venv/bin/python -u scripts/kakao_send_test.py --boundary
        kakao_len이 정확히 200인 본문을 보낸다. **상한 실측용이다** —
        카카오가 글자를 어느 단위로 세고 200이 포함인지 확인한다.

## 발송 성공은 링크를 보장하지 않는다

`result_code: 0`은 메시지가 도착했다는 뜻일 뿐이다. 카톡 메시지에는
링크가 **둘** 있고, 우리가 정할 수 있는 것은 하나뿐이다.

  - [전체 보기] 버튼  → 템플릿의 link.web_url  → **그 날짜** 고정 주소
  - 하단 "IT 브리핑 >" → 콘솔의 등록 웹 도메인 → 호스트 루트 = **최신**

콘솔은 경로를 무시한다(2026-11-17 실측). 그래서 하단 행은 항상 루트다.
둘을 같게 둘 이유가 없어 버튼에는 날짜를 박는다 — 사흘 뒤에 눌러도 그날
브리핑이 열린다.

그래서 마지막에 사람이 폰에서 **둘 다** 눌러야 한다.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from pipeline.lib.kakao import access_token, should_store
from pipeline.lib.sender import (
    KAKAO_MAX_TEXT,
    KakaoSender,
    build_kakao_text,
    kakao_len,
)
from pipeline.models import (
    Article,
    Briefing,
    RankedItem,
    RawBundle,
    RawItem,
    Summary,
)


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def _briefing(headlines: list[str], *, briefing_date: str, total: int) -> Briefing:
    """헤드라인만으로 Briefing을 꾸민다.

    **window_end를 UTC 22:20으로 둔다.** cron이 `20 22 * * 0-4`라서 그게
    실제 값이고, KakaoSender가 KST로 바꿔 읽어야 briefing_date가 나온다.
    여기를 KST로 적어 두면 2026-11-17에 고친 날짜 버그를 다시 못 잡는다.

    즉 이 함수는 "전날 22:20 UTC"를 일부러 만든다 — 그 시각의 KST 날짜가
    briefing_date다.
    """
    # briefing_date 07:20 KST → 그 시각의 UTC(= 전날 22:20). 그게 실제 값이다.
    kst_day = datetime.fromisoformat(f"{briefing_date}T07:20:00+09:00")
    window_end = kst_day.astimezone(timezone.utc).isoformat()

    summaries = [
        Summary(
            article=Article(
                ranked=RankedItem(
                    item=RawItem(
                        source="확인용", title=headline,
                        url="https://example.com/a",
                        published=window_end, excerpt="발췌",
                    ),
                    score=90, reason="확인용", topic="backend",
                ),
                body="본문", body_source="trafilatura", fallback_reason=None,
            ),
            headline=headline,
            bullets=["요점"],
            why_it_matters="확인용",
        )
        for headline in headlines
    ]
    # total이 보여 줄 건수보다 많으면 "외 N건"이 붙는다. 그 N을 만들기 위해
    # 나머지는 빈 자리로 채우지 않고 summaries 길이로만 센다 — KakaoSender가
    # len(summaries)를 total로 쓰기 때문이다.
    while len(summaries) < total:
        summaries.append(summaries[-1])

    return Briefing(
        window_start=window_end, window_end=window_end,
        summaries=summaries, considered=total,
    )


def _raw() -> RawBundle:
    now = datetime.now().isoformat()
    return RawBundle(
        window_start=now, window_end=now, items=[],
        source_counts={}, errors=[],
    )


def main() -> int:
    boundary = "--boundary" in sys.argv
    env = load_env()

    page = env.get("PAGE_URL", "").strip()
    if not page:
        raise SystemExit(
            ".env에 PAGE_URL이 없다.\n"
            "Vercel 프로덕션 주소를 넣는다. 예: PAGE_URL=https://xxx.vercel.app"
        )

    from supabase import create_client

    client = create_client(env["SUPABASE_URL"], env["SUPABASE_SECRET_KEY"])
    rows = client.table("kakao_auth").select("refresh_token").eq("id", 1).execute()
    if not rows.data:
        raise SystemExit("kakao_auth에 행이 없다. scripts/kakao_auth.py를 먼저 돌린다.")

    print("1) refresh_token으로 access_token 받기...")
    tokens = access_token(
        refresh_token=rows.data[0]["refresh_token"],
        client_id=env["KAKAO_REST_API_KEY"],
        client_secret=env["KAKAO_CLIENT_SECRET"],
    )
    print(f"   ✓ 받았다 ({len(tokens.access_token)}자)")

    if should_store(tokens):
        # 왔는데 저장하지 않으면 다음 달에 로그인이 끊긴다. 이 스크립트가
        # secret 키를 쥔 유일한 곳이므로 여기서 저장한다.
        client.table("kakao_auth").update(
            {"refresh_token": tokens.refresh_token,
             "refresh_token_expires_in": tokens.refresh_token_expires_in}
        ).eq("id", 1).execute()
        print(f"   ✓ refresh_token이 회전됐다 — 저장했다 "
              f"(만료 {tokens.refresh_token_expires_in}초)")
    else:
        print("   refresh_token 회전 없음 (만료가 1개월 넘게 남았다 — 정상)")

    # --- 본문을 고른다 ---
    print()
    if boundary:
        print("2) 경계 본문 만들기 (상한 실측)...")
        # kakao_len이 정확히 KAKAO_MAX_TEXT가 되는 조합이다.
        # 2026-11-17 실측: 헤드라인 30자 × 5건 + 발행 12건 → UTF-16 200단위.
        # 2026-11-17 실측으로 kakao_len == 200이 되는 유일한 조합:
        # 헤드라인 30자 × 5건 + 발행 12건. 29자면 196, 31자면 5건이 안 들어간다.
        headline = "경계 확인용 더미 헤드라인" + "가" * 16
        assert len(headline) == 30, f"{len(headline)}자 — 30이어야 한다"
        headlines = [headline] * 5
        briefing_date = "2026-11-12"
        total = 12
    else:
        print("2) Supabase에서 최신 브리핑 읽기...")
        rows = (
            client.table("articles")
            .select("briefing_date, headline, score")
            .order("briefing_date", desc=True)
            .order("score", desc=True)
            .limit(20)
            .execute()
        )
        items = rows.data or []
        if not items:
            raise SystemExit("   ★ articles가 비었다. 파이프라인을 먼저 돌린다.")
        briefing_date = items[0]["briefing_date"]
        same_day = [r["headline"] for r in items if r["briefing_date"] == briefing_date]
        headlines = same_day[:5]
        total = len(same_day)
        print(f"   {briefing_date} · 발행 {total}건 · 상위 {len(headlines)}건을 싣는다")

    # 보낼 본문을 미리 센다. KakaoSender가 조립할 것과 같은 값이다.
    preview = build_kakao_text(briefing_date, headlines, total=total)
    counted = kakao_len(preview)
    print(f"   len() {len(preview)}자 / kakao_len {counted}단위 (상한 {KAKAO_MAX_TEXT})")
    if counted > KAKAO_MAX_TEXT:
        raise SystemExit("   ★ 조립이 상한을 넘겼다 — build_kakao_text 버그다")
    print()
    for line in preview.splitlines():
        print(f"   │ {line}")

    # --- 보낸다 ---
    print()
    print("3) KakaoSender로 보내기...")
    briefing = _briefing(headlines, briefing_date=briefing_date, total=total)
    KakaoSender(access_token=tokens.access_token, page_url=page).send(
        briefing=briefing, raw=_raw()
    )
    print("   ✓ 보냈다 (거부되면 여기서 Permanent/Transient로 멈춘다)")

    print()
    print("─" * 62)
    print("카카오톡 '나와의 채팅'에서 **두 링크를 모두** 눌러 본다.")
    print()
    day_url = f"{page.rstrip('/')}/{briefing_date}"
    print(f"  [전체 보기] 버튼   → {day_url}")
    print(f"                       (그날 고정. 템플릿 link.web_url)")
    print(f"  하단 'IT 브리핑 >' → {page.rstrip('/')}/")
    print(f"                       (최신. 콘솔의 등록 웹 도메인 — 경로를 무시한다)")
    print()
    print(f"  날짜가 {briefing_date[5:].replace('-', '/')}로 찍혀 있어야 한다.")
    print("  (window_end는 UTC라 변환을 빼먹으면 전날이 찍힌다)")
    if boundary:
        print()
        print("  이 메시지가 도착했다면 상한 200이 **포함**이고")
        print("  UTF-16 셈이 안전하다는 뜻이다.")
    print("─" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
