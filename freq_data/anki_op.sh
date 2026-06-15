#!/usr/bin/env bash
# Safe wrapper for collection.anki2 mutations.
#   backup  ->  stop anki-bot  ->  wait for lock to clear  ->  run op  ->  restart anki-bot
#
# The op SCRIPT must do its own verification (print results) BEFORE this returns,
# because the bot is restarted only after the script exits (one stopped-bot window).
#
# Usage:  anki_op.sh <label> <python_script> [args...]
#   e.g.  anki_op.sh gap-gen freq_data/apply_gaps.py --apply
set -uo pipefail
ROOT=/home/vincent/anki-headless
PY="$ROOT/.venv/bin/python"
COL="$ROOT/collection.anki2"

LABEL="${1:?usage: anki_op.sh <label> <script> [args...]}"; shift
SCRIPT="${1:?usage: anki_op.sh <label> <script> [args...]}"; shift

TS=$(date +%Y%m%d-%H%M%S)
BAK="$ROOT/backups/collection.anki2.${TS}.${LABEL}.bak"
echo "[anki_op] backup -> $(basename "$BAK")"
cp "$COL" "$BAK" || { echo "[anki_op] backup FAILED, aborting"; exit 1; }

# stop the bot only if it is currently online
BOT_UP=0
if pm2 pid anki-bot >/dev/null 2>&1 && [ -n "$(pm2 pid anki-bot 2>/dev/null | tr -d '[:space:]')" ]; then
  BOT_UP=1; echo "[anki_op] stopping anki-bot"; pm2 stop anki-bot >/dev/null 2>&1
fi

echo "[anki_op] waiting for collection lock to clear..."
"$PY" - "$COL" <<'PYWAIT'
import sys, time
from anki.collection import Collection
col_path = sys.argv[1]
for _ in range(30):
    try:
        c = Collection(col_path); c.close(); print("[anki_op] lock clear"); sys.exit(0)
    except Exception:
        time.sleep(1)
print("[anki_op] ERROR: lock did not clear in 30s"); sys.exit(1)
PYWAIT
if [ $? -ne 0 ]; then
  [ "$BOT_UP" = 1 ] && pm2 start anki-bot >/dev/null 2>&1
  exit 1
fi

echo "[anki_op] running: $SCRIPT $*"
"$PY" "$SCRIPT" "$@"
RC=$?

[ "$BOT_UP" = 1 ] && { echo "[anki_op] restarting anki-bot"; pm2 start anki-bot >/dev/null 2>&1; }
echo "[anki_op] done (op exit=$RC, backup=$(basename "$BAK"))"
exit $RC
