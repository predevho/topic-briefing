#!/usr/bin/env bash
# anon(브라우저) 권한이 설계대로인지 확인한다.
#
# 왜 필요한가: 리포지토리가 퍼블릭이고 페이지도 공개 URL이다. article_bodies
# (타인의 기사 본문 전문)가 anon에게 열려 있으면 그 사이트는 남의 기사를
# 재배포하는 사이트가 된다. 그리고 **테이블이 비어 있는 동안에는 증상이
# 나타나지 않는다** — 데이터가 쌓인 뒤 발견하면 이미 공개돼 있던 것이다.
#
# 2026-11-17 개정: 페이지가 Supabase를 직접 조회하게 되면서 권한이 바뀌었다.
#   - articles·runs가 **컬럼 단위**로 열렸다 (reason·errors는 막혀 있다)
#   - reactions·notes 쓰기가 authenticated로 옮겨갔다 (anon은 거부)
#   - clicks만 anon 삽입이 남았다 (로그인 전에도 눌리므로)
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

# 페이지가 실제로 읽는 컬럼. web/src/lib/data.ts와 맞춰야 한다.
ART_COLS="id,briefing_date,url,source,published_at,headline,bullets,why_it_matters,topic,score,position"
RUN_COLS="briefing_date,status,collected_count,considered_count,max_score,published_count,source_counts"

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

# $1 = 테이블/뷰, $2 = select 목록
get() { curl -s -o "$TMP" -w '%{http_code}' "$B/$1?select=$2&limit=1" \
          -H "apikey: $PUB" -H "Authorization: Bearer $PUB"; }

# $1 = 테이블, $2 = JSON 본문
post() { curl -s -o "$TMP" -w '%{http_code}' -X POST "$B/$1" \
          -H "apikey: $PUB" -H "Authorization: Bearer $PUB" \
          -H "Content-Type: application/json" -H "Prefer: return=minimal" \
          -d "$2"; }

# --- 1. 페이지가 읽어야 하는 것 ---
echo
echo "1. anon이 읽어야 하는 것 (페이지가 쓰는 컬럼만)"
C=$(get articles "$ART_COLS")
if [ "$C" = "200" ]; then note "✓ articles (페이지 컬럼)"
else bad "articles가 안 읽힌다 (HTTP $C, $(code_of)) — 페이지가 빈다"; fi

C=$(get runs "$RUN_COLS")
if [ "$C" = "200" ]; then note "✓ runs (0건인 날의 수치, 요구사항 D8)"
else bad "runs가 안 읽힌다 (HTTP $C, $(code_of)) — 0건인 날이 아카이브에서 사라진다"; fi

C=$(get briefing_index "briefing_date,count,lead")
if [ "$C" = "200" ]; then note "✓ briefing_index (아카이브용 뷰)"
else bad "briefing_index가 안 읽힌다 (HTTP $C, $(code_of)) — 아카이브가 빈다"; fi

# --- 2. 테이블 단위로 막혀야 하는 것 ---
# 200이 아닌지로 판정한다. PostgREST가 권한 거부에 401을 줄 때도 403을 줄
# 때도 있어서 특정 상태 코드에 묶으면 깨지기 쉽다.
echo
echo "2. anon이 전면 차단되어야 하는 것"
for t in article_bodies kakao_auth; do
  C=$(get "$t" '*')
  if [ "$C" = "200" ]; then bad "$t 가 읽힌다! (HTTP 200) — 즉시 고쳐야 한다"
  else note "✓ $t 차단 (HTTP $C, $(code_of))"; fi
done

# notes는 이제 authenticated만 읽는다. anon으로는 막혀야 한다.
C=$(get notes '*')
if [ "$C" = "200" ]; then bad "notes가 anon에게 읽힌다 (HTTP 200) — 내 메모가 공개된다"
else note "✓ notes 차단 (HTTP $C, $(code_of))"; fi

# --- 3. 컬럼 단위 차단 ---
# 테이블은 열려 있고 특정 컬럼만 막힌 경우다. 테이블 단위 검사로는
# 절대 안 잡히므로 컬럼을 하나씩 직접 찔러 본다.
echo
echo "3. 컬럼 단위 차단 (테이블은 열려 있다)"
C=$(get articles reason)
if [ "$C" = "200" ]; then bad "articles.reason이 읽힌다 — LLM 판단 근거가 공개된다"
else note "✓ articles.reason 차단 (HTTP $C, $(code_of))"; fi

for col in errors input_tokens output_tokens window_start; do
  C=$(get runs "$col")
  if [ "$C" = "200" ]; then bad "runs.$col 이 읽힌다 — 내부 기록이 공개된다"
  else note "✓ runs.$col 차단 (HTTP $C, $(code_of))"; fi
done

# select=* 는 참고용이다. PostgREST가 권한 있는 컬럼만 펼치는지,
# SELECT * 를 그대로 보내 거부되는지가 버전에 따라 다르다. 위의 컬럼별
# 검사가 실제 판정이므로 여기서는 결과만 적어 둔다.
C=$(get articles '*')
note "· articles?select=* → HTTP $C (참고. 판정은 위의 컬럼별 검사다)"

# --- 4. 쓰기 ---
# 없는 article_id를 쓴다. 정책을 통과하면 외래 키(23503)에서 걸리고,
# 정책이 막으면 42501이 된다. 어느 경로든 행은 만들어지지 않으므로
# 운영 데이터를 건드리지 않고 정책의 방향만 확인할 수 있다.
GHOST=999999999

echo
echo "4. anon 쓰기 — 좋아요와 메모는 로그인해야 한다"
C=$(post reactions "{\"article_id\":$GHOST}")
K=$(code_of)
case "$K" in
  42501) note "✓ reactions 삽입 차단 ($K) — 낯선 사람의 신호 오염이 막힌다" ;;
  23503) bad "reactions 정책을 통과해 외래 키에서 걸렸다 ($K) — anon이 좋아요를 넣는다" ;;
  *)     bad "reactions: 예상 못 한 응답 (HTTP $C, code=$K)" ;;
esac

C=$(post notes "{\"article_id\":$GHOST,\"text\":\"x\"}")
K=$(code_of)
case "$K" in
  42501) note "✓ notes 삽입 차단 ($K)" ;;
  23503) bad "notes 정책을 통과했다 ($K) — anon이 메모를 남긴다" ;;
  *)     bad "notes: 예상 못 한 응답 (HTTP $C, code=$K)" ;;
esac

# --- 5. clicks는 로그인 전에도 기록되어야 한다 ---
echo
echo "5. clicks — 로그인 전 클릭도 기록되어야 한다"
C=$(post clicks "{\"article_id\":$GHOST}")
K=$(code_of)
case "$K" in
  23503) note "✓ 정책 통과, 외래 키에서 걸렸다 ($K)" ;;
  42501) bad "정책이 막았다 ($K) — 로그인 전 클릭이 기록되지 않는다" ;;
  *)     bad "clicks: 예상 못 한 응답 (HTTP $C, code=$K)" ;;
esac

echo
echo "6. 위장 방지 — anon이 user_id를 채운 삽입은 거부되어야 한다"
C=$(post clicks "{\"article_id\":$GHOST,\"user_id\":\"00000000-0000-0000-0000-000000000001\"}")
K=$(code_of)
case "$K" in
  42501) note "✓ 정책이 막았다 ($K)" ;;
  23503) bad "정책을 통과해 외래 키에서 걸렸다 ($K) — user_id 위장이 가능하다" ;;
  *)     bad "예상 못 한 응답 (HTTP $C, code=$K)" ;;
esac

echo
if [ "$FAIL" = "0" ]; then
  echo "전부 통과. anon 권한이 설계대로다."
else
  echo "실패가 있다. supabase/schema.sql의 revoke/grant/policy를 확인한다."
fi
exit "$FAIL"
