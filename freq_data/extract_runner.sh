#!/usr/bin/env bash
# Supervises phase-2 OCR: N sharded workers, each auto-restarting (fully resumable)
# until its shard reports .done. Niced to yield to the box's PM2 services. Launch
# with setsid+nohup so it outlives the shell. Self-exits when all shards complete.
set -u
ROOT=/home/vincent/anki-headless
PY="$ROOT/.venv/bin/python"
OCR="$ROOT/freq_data/ocr"
N=4
LOG="$OCR/_extract_runner.log"
echo "[$(date '+%F %T')] RUNNER START ($N OCR shards, pid $$)" >> "$LOG"

run_shard () {
  local s=$1
  local i
  for i in $(seq 1 100000); do
    [ -f "$OCR/_shard${s}of${N}.done" ] && { echo "[$(date '+%T')] shard $s reported DONE" >> "$LOG"; break; }
    echo "[$(date '+%F %T')] shard $s launch #$i" >> "$LOG"
    nice -n 15 "$PY" "$ROOT/freq_data/extract_corpus.py" --of "$N" --shard "$s" --budget 600 >> "$LOG" 2>&1
    rc=$?
    if [ "$rc" = 3 ]; then sleep 60; else sleep 3; fi
  done
}

for s in $(seq 0 $((N - 1))); do run_shard "$s" & done
wait
echo "[$(date '+%F %T')] RUNNER: ALL SHARDS COMPLETE" >> "$LOG"
