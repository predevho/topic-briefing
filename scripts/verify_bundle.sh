#!/usr/bin/env bash
# 빌드 산출물에 비밀이 섞여 들어갔는지 확인한다.
#
# 왜 필요한가: 번들은 공개 URL에서 서빙된다. publishable 키는
# **들어가야 정상**이고(브라우저가 Supabase에 직접 붙는다), secret 키는
# **절대 들어가면 안 된다**(RLS를 우회한다).
#
# 산출물은 web/dist다. Vercel이 푸시를 받고 직접 빌드하므로 커밋하지
# 않는다 — 그래서 배포 전에 로컬에서 이 검사를 돌려야 한다.
#
# 2026-11-17: 단순히 `grep sb_secret_`로 보면 **거짓 경보가 난다.**
# supabase-js 자신이 키 형식을 판별하려고 그 리터럴을 들고 있다:
#
#     e.startsWith(`sb_publishable_`) || e.startsWith(`sb_secret_`)
#
# 그래서 두 가지로 판정한다.
#   1) .env의 **실제 키 값**이 번들에 있는가 (이것이 결정적이다)
#   2) sb_secret_ 뒤에 키처럼 긴 문자열이 붙어 있는가
#      (라이브러리 리터럴은 바로 뒤가 백틱이라 걸리지 않는다)
#
# 실행: bash scripts/verify_bundle.sh
set -uo pipefail

cd "$(dirname "$0")/.."

if ! ls web/dist/assets/*.js >/dev/null 2>&1; then
  echo "★ web/dist/assets에 번들이 없다. 먼저 'cd web && npm run build'를 돌린다."
  exit 1
fi

python3 - <<'PY'
import re
import sys
from pathlib import Path

env = {}
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()

secret = env.get("SUPABASE_SECRET_KEY", "")
anthropic = env.get("ANTHROPIC_API_KEY", "")
publishable = env.get("VITE_SUPABASE_PUBLISHABLE_KEY", "")

files = sorted(Path("web/dist/assets").glob("*"))
blob = "\n".join(
    f.read_text(encoding="utf-8", errors="replace") for f in files if f.is_file()
)

fail = False

def check(label: str, bad: bool, detail: str = "") -> None:
    global fail
    if bad:
        print(f"  ★ {label} {detail}")
        fail = True
    else:
        print(f"  ✓ {label}")

# 1) 실제 키 값 — 결정적 판정
check("Supabase secret 키 없음", bool(secret) and secret in blob, "— 번들에 들어갔다")
check("Anthropic 키 없음", bool(anthropic) and anthropic in blob, "— 번들에 들어갔다")

# 2) 형태로 한 번 더. 라이브러리 리터럴(`sb_secret_` + 백틱)은 걸리지 않는다.
shaped = re.findall(r"sb_secret_[A-Za-z0-9_-]{8,}", blob)
check("secret 키 형태 없음", bool(shaped), f"— {len(shaped)}건: {shaped[:2]}")

shaped_ant = re.findall(r"sk-ant-[A-Za-z0-9_-]{8,}", blob)
check("Anthropic 키 형태 없음", bool(shaped_ant), f"— {len(shaped_ant)}건")

# 3) publishable 키는 **있어야** 정상이다. 없으면 .env.local이 빌드에
#    안 들어간 것이고, 배포하면 페이지가 빈다.
if publishable:
    check("publishable 키 있음 (의도된 노출)", publishable not in blob,
          "— 없다. web/.env.local을 확인한다")

print()
if fail:
    print("실패가 있다. 배포하지 않는다.")
    sys.exit(1)
print("번들이 안전하다.")
PY
