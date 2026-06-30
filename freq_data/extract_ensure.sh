#!/usr/bin/env bash
# Idempotent guard: make sure the OCR runner is alive until all shards are done.
# Safe to call repeatedly (cron) and at boot. Does nothing once extraction completes.
ROOT=/home/vincent/anki-headless
OCR="$ROOT/freq_data/ocr"
N=4
done=0
for s in $(seq 0 $((N - 1))); do
  [ -f "$OCR/_shard${s}of${N}.done" ] && done=$((done + 1))
done
[ "$done" = "$N" ] && exit 0                       # all shards complete -> nothing to do
pgrep -f "extract_runner.sh" >/dev/null && exit 0  # already running
cd "$ROOT" && setsid nohup bash freq_data/extract_runner.sh >/dev/null 2>&1 &
echo "[$(date '+%F %T')] extract_ensure: (re)launched runner" >> "$OCR/_extract_runner.log"
