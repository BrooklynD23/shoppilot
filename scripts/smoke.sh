#!/usr/bin/env bash
# Usage: smoke.sh BASE_URL [EXPECTED_SHA] [TIMEOUT_S=600]
# SMOKE_FULL=1 adds session/store/bad-cookie checks (P7-D3); cookie jar at SMOKE_JAR.
# Never calls /api/plan (spends LLM money).
set -euo pipefail
BASE="${1:?usage: smoke.sh BASE_URL [EXPECTED_SHA] [TIMEOUT_S]}"
BASE="${BASE%/}"
SHA="${2:-}"
TIMEOUT="${3:-600}"
WANT="${SHA:0:7}"
end=$((SECONDS + TIMEOUT))
last=""

check() {
  local h home
  h=$(curl -fsS --max-time 15 "$BASE/healthz") || { last="${h:-healthz unreachable}"; return 1; }
  last="$h"
  [ -z "$WANT" ] || grep -q "\"version\": *\"$WANT\"" <<<"$h" || return 1
  home=$(curl -fsS --max-time 15 "$BASE/") || { last="/ unreachable"; return 1; }
  grep -q ShopPilot <<<"$home" || { last="/ missing ShopPilot"; return 1; }
}

while ! check 2>/dev/null; do
  if [ "$SECONDS" -ge "$end" ]; then
    echo "smoke FAILED after ${TIMEOUT}s; last response: $last" >&2
    echo "$last"
    exit 1
  fi
  sleep "$(( TIMEOUT < 10 ? 1 : 10 ))"
done
echo "smoke OK ($BASE${WANT:+ @ $WANT})"
[ "${SMOKE_FULL:-}" = 1 ] || exit 0

JAR="${SMOKE_JAR:-/tmp/sp.jar}"
fail() { echo "smoke FAILED (full): $1" >&2; exit 1; }
rm -f "$JAR"
curl -fsS --max-time 15 -c "$JAR" -X POST -H 'X-ShopPilot: 1' "$BASE/api/session" >/dev/null \
  || fail "POST /api/session"
store=$(curl -fsS --max-time 15 -b "$JAR" "$BASE/api/store") || fail "GET /api/store"
grep -q '"products"' <<<"$store" || fail "/api/store missing products: ${store:0:200}"
code=$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' \
  -H 'Cookie: sp_session=garbage' "$BASE/api/store") || fail "GET /api/store (garbage cookie)"
[ "$code" = 401 ] || fail "garbage cookie got $code, want 401"
echo "smoke FULL OK (jar: $JAR)"
