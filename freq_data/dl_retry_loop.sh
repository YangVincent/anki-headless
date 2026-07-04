#!/usr/bin/env bash
# Auto-retry loop: resume the resilient Drive-folder download every 30 min,
# skipping already-downloaded files, until all 387 are present (or 48 rounds).
set -u
ROOT=/home/vincent/anki-headless
PY="$ROOT/.venv/bin/python"
FOLDER=1-OWaHNAMQ02JOIhudegbBI7vZsx100MP
OUT="$ROOT/freq_data/textbooks"
BASE="$OUT/Learning Mandarin Material (DO NOT SELL) @binkybing"
LOG="$ROOT/freq_data/textbooks/dl_retry.log"

for round in $(seq 1 48); do
  have=$(find "$BASE" -type f -size +0c 2>/dev/null | wc -l)
  echo "[$(date '+%F %T')] round $round — have $have/387" >> "$LOG"
  if [ "$have" -ge 387 ]; then echo "[$(date '+%F %T')] COMPLETE" >> "$LOG"; break; fi
  "$PY" "$ROOT/freq_data/dl_folder_resilient.py" "$FOLDER" "$OUT" >> "$LOG" 2>&1
  sleep 1800
done
echo "[$(date '+%F %T')] loop ended" >> "$LOG"
