"""카카오 발송 경로를 한 번 확인한다.

**이것은 KakaoSender가 아니다.** 200자 조립과 "외 N건" 접기는 계획 3에서
설계한 뒤 만든다. 여기서는 세 가지만 본다.

  1. Supabase의 refresh_token으로 access_token을 받을 수 있는가
  2. 기본 텍스트 템플릿이 "나와의 채팅"에 도착하는가
  3. 버튼이 페이지로 연결되는가

실행: .venv/bin/python -u scripts/kakao_send_test.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
# 페이지 주소는 .env의 PAGE_URL에서 읽는다. 계획 3의 KakaoSender도
# 같은 값을 쓰므로 하드코딩하지 않는다.


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def main() -> int:
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
    refresh_token = rows.data[0]["refresh_token"]

    print("1) refresh_token으로 access_token 받기...")
    response = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": env["KAKAO_REST_API_KEY"],
            "client_secret": env["KAKAO_CLIENT_SECRET"],
            "refresh_token": refresh_token,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        timeout=20.0,
    )
    if response.status_code != 200:
        raise SystemExit(f"   ★ 실패 (HTTP {response.status_code}): {response.text}")
    tokens = response.json()
    access_token = tokens["access_token"]
    print(f"   ✓ 받았다 ({len(access_token)}자)")

    # 스펙 6.3: 새 refresh_token은 기존 만료가 1개월 미만일 때만 온다.
    # 지금은 60일 남았으므로 안 오는 것이 정상이다.
    rotated = "refresh_token" in tokens
    print(f"   refresh_token 갱신됨: {'예 — 저장이 필요하다' if rotated else '아니오 (만료 60일 남음, 정상)'}")

    print()
    print("2) 나에게 메시지 보내기...")
    template = {
        "object_type": "text",
        "text": (
            "📡 연결 확인\n\n"
            "카카오 발송 경로가 동작합니다.\n"
            "브리핑은 계획 3에서 이 자리에 들어갑니다."
        ),
        "link": {"web_url": page, "mobile_web_url": page},
        "button_title": "전체 보기",
    }

    # 글자 수를 미리 센다. 기본 텍스트 템플릿의 text는 200자가 상한이고,
    # 넘으면 거부된다(스펙 6.1).
    print(f"   text 길이: {len(template['text'])}자 (상한 200)")

    # **form-urlencoded에 template_object를 JSON 문자열로 넣는다.**
    # 본문 전체를 JSON으로 보내면 받지 않는다.
    response = httpx.post(
        SEND_URL,
        data={"template_object": json.dumps(template, ensure_ascii=False)},
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        },
        timeout=20.0,
    )
    if response.status_code != 200:
        raise SystemExit(
            f"   ★ 실패 (HTTP {response.status_code}): {response.text}\n\n"
            "403이면 동의항목을 확인한다:\n"
            "  제품 설정 → 카카오 로그인 → 동의항목 → [접근권한] 카카오톡 메시지 전송"
        )

    print(f"   ✓ 보냈다. 응답: {response.json()}")
    print()
    print("카카오톡 '나와의 채팅'을 확인한다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
