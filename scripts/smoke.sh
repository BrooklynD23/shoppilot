#!/usr/bin/env bash
# Usage: smoke.sh BASE_URL [EXPECTED_SHA] [TIMEOUT_S=600]
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
# SMOKE_FULL=1 extra checks are added by task P7-D3.
