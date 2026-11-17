"""카카오 최초 인증 — refresh_token을 받아 Supabase에 저장한다.

**한 번만 돌린다.** 그 뒤로는 파이프라인이 refresh_token으로 매일
access_token을 받아 쓴다(스펙 6.3).

왜 수동인가: 카카오 OAuth는 사용자가 브라우저에서 동의해야 하고, 그
동의는 사람만 할 수 있다. 서버에서 자동으로 받을 방법이 없다.

실행: .venv/bin/python scripts/kakao_auth.py
"""

from __future__ import annotations

import os
import sys
import urllib.parse
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx

# 카카오 개발자 콘솔의 Redirect URI와 **글자 하나까지 같아야 한다.**
# 다르면 KOE006(redirect_uri mismatch)이 난다.
REDIRECT_URI = "http://localhost:5174/kakao/callback"
PORT = 5174

AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"

# "나에게 보내기"에 필요한 유일한 권한. 친구목록은 받지 않는다 —
# 그건 친구 발송용이고 별도 심사가 필요하다.
SCOPE = "talk_message"


def load_env() -> dict[str, str]:
    """.env를 읽는다. python-dotenv를 쓰지 않는 이유는 이 스크립트가
    파이프라인 밖에 있고 의존성을 늘릴 이유가 없어서다.
    """
    env: dict[str, str] = {}
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


class CallbackHandler(BaseHTTPRequestHandler):
    """인가 코드를 한 번 받고 끝나는 핸들러.

    `code`를 클래스 속성에 담는 이유: HTTPServer가 요청마다 핸들러를
    새로 만들기 때문에 인스턴스 변수로는 밖에서 읽을 수 없다.
    """

    code: str | None = None
    error: str | None = None

    def do_GET(self) -> None:  # noqa: N802  (BaseHTTPRequestHandler의 이름 규칙)
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)

        CallbackHandler.code = (params.get("code") or [None])[0]
        CallbackHandler.error = (params.get("error_description") or params.get("error") or [None])[0]

        body = (
            "<h2>인증을 받았습니다. 터미널로 돌아가세요.</h2>"
            if CallbackHandler.code
            else f"<h2>실패: {CallbackHandler.error}</h2>"
        )
        payload = f"<html><meta charset='utf-8'><body>{body}</body></html>".encode()

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        """기본 구현이 요청 줄을 stderr에 찍는다. 인가 코드가 URL에
        들어 있으므로 로그에 남기지 않는다.
        """


def get_code(client_id: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
    }
    url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    print("브라우저에서 카카오 동의 화면을 엽니다.")
    print("안 열리면 아래 주소를 직접 붙여 넣으세요.\n")
    print(f"  {url}\n")

    server = HTTPServer(("localhost", PORT), CallbackHandler)
    webbrowser.open(url)

    print(f"localhost:{PORT}에서 기다리는 중...")
    # 한 번만 처리하고 끝낸다. 콜백은 한 번 오면 되고, 서버를 계속
    # 열어 둘 이유가 없다.
    server.handle_request()
    server.server_close()

    if CallbackHandler.error:
        raise SystemExit(f"카카오가 거부했다: {CallbackHandler.error}")
    if not CallbackHandler.code:
        raise SystemExit("인가 코드를 받지 못했다.")
    return CallbackHandler.code


def exchange(code: str, client_id: str, client_secret: str) -> dict:
    # **form-urlencoded로 보낸다.** 카카오 토큰 엔드포인트는 JSON을 받지 않는다.
    # httpx에서 data=는 form, json=은 JSON이다.
    response = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "code": code,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        timeout=20.0,
    )
    if response.status_code != 200:
        # 본문에 토큰이 없으므로(실패했으니) 그대로 보여 줘도 안전하다.
        raise SystemExit(f"토큰 발급 실패 (HTTP {response.status_code}): {response.text}")
    return response.json()


def main() -> int:
    env = load_env()
    client_id = env.get("KAKAO_REST_API_KEY", "")
    client_secret = env.get("KAKAO_CLIENT_SECRET", "")
    supabase_url = env.get("SUPABASE_URL", "")
    supabase_key = env.get("SUPABASE_SECRET_KEY", "")

    missing = [
        name
        for name, value in [
            ("KAKAO_REST_API_KEY", client_id),
            ("KAKAO_CLIENT_SECRET", client_secret),
            ("SUPABASE_URL", supabase_url),
            ("SUPABASE_SECRET_KEY", supabase_key),
        ]
        if not value
    ]
    if missing:
        raise SystemExit(f".env에 없다: {', '.join(missing)}")

    code = get_code(client_id)
    print("인가 코드를 받았다. 토큰으로 교환한다...")
    tokens = exchange(code, client_id, client_secret)

    # **동의항목을 안 켰으면 여기서 잡는다.** 이 검사가 없으면 토큰은
    # 멀쩡히 받고 나중에 발송할 때 403이 나서 원인을 찾기 어렵다.
    granted = (tokens.get("scope") or "").split()
    if SCOPE not in granted:
        raise SystemExit(
            f"받은 권한에 {SCOPE}가 없다: {granted or '(없음)'}\n\n"
            "카카오 개발자 콘솔에서 확인한다:\n"
            "  제품 설정 → 카카오 로그인 → 동의항목\n"
            "  → [접근권한] 카카오톡 메시지 전송을 설정"
        )

    refresh_token = tokens["refresh_token"]
    # 수명을 하드코딩하지 않는다. 카카오가 초 단위로 내려준다(스펙 6.3).
    expires_in = int(tokens["refresh_token_expires_in"])
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    from supabase import create_client

    client = create_client(supabase_url, supabase_key)
    client.table("kakao_auth").upsert(
        {
            "id": 1,
            "refresh_token": refresh_token,
            "refresh_token_expires_at": expires_at.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()

    # 토큰 값은 찍지 않는다. 길이와 만료만 보여 준다.
    print()
    print("저장했다.")
    print(f"  권한            {' '.join(granted)}")
    print(f"  refresh_token   {len(refresh_token)}자 (Supabase kakao_auth에 저장)")
    print(f"  만료            {expires_at.date()} ({expires_in // 86400}일 뒤)")
    print()
    print("다음: .venv/bin/python scripts/kakao_send_test.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
