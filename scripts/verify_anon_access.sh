#!/usr/bin/env bash
# anon(브라우저) 권한이 설계대로인지 확인한다.
#
# 왜 필요한가: 리포지토리가 퍼블릭이고 페이지도 공개 URL이다. article_bodies
# (타인의 기사 본문 전문)가 anon에게 열려 있으면 그 사이트는 남의 기사를
# 재배포하는 사이트가 된다. 그리고 **테이블이 비어 있는 동안에는 증상이
# 나타나지 않는다** — 데이터가 쌓인 뒤 발견하면 이미 공개돼 있던 것이다.
#
# 스키마나 정책을 고칠 때마다 다시 돌린다.
#
# 실행: bash scripts/verify_anon_access.sh
set -uo pipefail

cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

PUB="${VITE_SUPABASE_PUBLISHABLE_KEY:-${SUPABASE_KEY:-}}"
B="${SUPABASE_URL%/}/rest/v1"
TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
FAIL=0

note() { printf '  %s\n' "$1"; }
bad()  { printf '  ★ %s\n' "$1"; FAIL=1; }

# --- 0. 어떤 키인지 ---
echo "0. 키 판별"
case "$PUB" in
  sb_publishable_*) note "✓ publishable 키 (현행)" ;;
  eyJ*)             note "~ 레거시 anon JWT. 이 검증엔 유효하나 2026년 말 폐지" ;;
  sb_secret_*)      bad "secret 키다 — RLS를 우회하므로 이 검증이 무의미하다"; exit 1 ;;
  "")               bad "VITE_SUPABASE_PUBLISHABLE_KEY가 .env에 없다"; exit 1 ;;
  *)                note "? 형식 불명" ;;
esac

code_of() { python3 -c "
import json
try: print(json.load(open('$TMP')).get('code') or '-')
except Exception: print('-')"; }

get() { curl -s -o "$TMP" -w '%{http_code}' "$B/$1?select=*&limit=1" \
          -H "apikey: $PUB" -H "Authorization: Bearer $PUB"; }

# --- 1. 읽혀야 하는 것 ---
echo
echo "1. anon이 읽어야 하는 것"
C=$(get articles)
if [ "$C" = "200" ]; then note "✓ articles"; else bad "articles가 안 읽힌다 (HTTP $C, $(code_of)) — 페이지가 빈다"; fi

# --- 2. 막혀야 하는 것 ---
# 200이 아닌지로 판정한다. PostgREST가 권한 거부에 401을 줄 때도 403을 줄
# 때도 있어서 특정 상태 코드에 묶으면 깨지기 쉽다.
echo
echo "2. anon이 막혀야 하는 것"
for t in article_bodies runs kakao_auth; do
  C=$(get "$t")
  if [ "$C" = "200" ]; then bad "$t 가 읽힌다! (HTTP 200) — 즉시 고쳐야 한다"
  else note "✓ $t 차단 (HTTP $C, $(code_of))"; fi
done

post() { curl -s -o "$TMP" -w '%{http_code}' -X POST "$B/reactions" \
          -H "apikey: $PUB" -H "Authorization: Bearer $PUB" \
          -H "Content-Type: application/json" -H "Prefer: return=minimal" \
          -d "$1"; }

# --- 3·4. 삽입 정책 ---
# 없는 article_id를 쓴다. 정책을 통과하면 외래 키(23503)에서 걸리고,
# 정책이 막으면 42501이 된다. 어느 경로든 행은 만들어지지 않으므로
# 운영 데이터를 건드리지 않고 정책의 방향만 확인할 수 있다.
GHOST=999999999

echo
echo "3. 위장 방지 — user_id를 채운 삽입은 거부되어야 한다"
C=$(post "{\"article_id\":$GHOST,\"user_id\":\"00000000-0000-0000-0000-000000000001\"}")
K=$(code_of)
case "$K" in
  42501) note "✓ 정책이 막았다 ($K)" ;;
  23503) bad "정책을 통과해 외래 키에서 걸렸다 ($K) — user_id 위장이 가능하다" ;;
  *)     bad "예상 못 한 응답 (HTTP $C, code=$K)" ;;
esac

echo
echo "4. 정상 좋아요 — user_id 없는 삽입은 통과해야 한다"
C=$(post "{\"article_id\":$GHOST}")
K=$(code_of)
case "$K" in
  23503) note "✓ 정책 통과, 외래 키에서 걸렸다 ($K)" ;;
  42501) bad "정책이 막았다 ($K) — 좋아요를 아무도 누를 수 없다" ;;
  *)     bad "예상 못 한 응답 (HTTP $C, code=$K)" ;;
esac

echo
if [ "$FAIL" = "0" ]; then
  echo "전부 통과. anon 권한이 설계대로다."
else
  echo "실패가 있다. supabase/schema.sql의 revoke/grant/policy를 확인한다."
fi
exit "$FAIL"
