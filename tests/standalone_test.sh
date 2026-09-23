#!/usr/bin/env bash
# Standalone smoke test — no aw-workspace runtime required.
#
# The template's version of this file installs a system CLI; this app has
# none, so it is repurposed to what actually matters here: boot standalone
# mode and prove the thing QA and `doctor` will poke is answering.
#
# Usage:
#   bash tests/standalone_test.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-9482}"
PY="${PY:-python3}"
# Never touch the real workspace data dir from a smoke test.
export AW_APP_UC_PHD_DATA_DIR="${AW_APP_UC_PHD_DATA_DIR:-$(mktemp -d)}"

echo "== booting standalone on 127.0.0.1:$PORT (data dir: $AW_APP_UC_PHD_DATA_DIR) =="
PORT="$PORT" "$PY" -m uc_phd_app >/tmp/uc-phd-standalone.log 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then break; fi
  sleep 1
done

echo "== /healthz =="
curl -fsS "http://127.0.0.1:$PORT/healthz"
echo

echo "== the seed landed in the data dir, not the package dir =="
test -f "$AW_APP_UC_PHD_DATA_DIR/cisuc.sqlite3"
test -f "$AW_APP_UC_PHD_DATA_DIR/seed.json"

echo "== one data endpoint, at both roots =="
curl -fsS "http://127.0.0.1:$PORT/api/coverage" >/dev/null
curl -fsS "http://127.0.0.1:$PORT/api/apps/aw-app-uc-phd/api/coverage" >/dev/null

echo "== the SPA is served, and the API is not shadowed by its static mount =="
curl -fsS "http://127.0.0.1:$PORT/" | grep -qi '<div id="root">'
curl -fsS -H 'Accept: application/json' "http://127.0.0.1:$PORT/api/groups" | grep -q '"groups"'

echo "OK: standalone boots, seeds, and serves both the API and the SPA"
