#!/usr/bin/env bash
# Auto-restart wrapper for the corpus OCR queue. Re-runs ocr_queue.py (resumable)
# until it logs QUEUE COMPLETE. Niced so it yields to the 12 PM2 services.
ROOT=/home/vincent/anki-headless
PY="$ROOT/.venv/bin/python"
PROG="$ROOT/freq_data/ocr/_queue_progress.log"
RUNLOG="$ROOT/freq_data/ocr/_runner.log"
for i in $(seq 1 2000); do
  if grep -q "QUEUE COMPLETE" "$PROG" 2>/dev/null; then
    echo "[runner] QUEUE COMPLETE — stopping" >> "$RUNLOG"; break
  fi
  echo "[runner $(date '+%F %T')] launch #$i" >> "$RUNLOG"
  nice -n 15 "$PY" "$ROOT/freq_data/ocr_queue.py" >> "$RUNLOG" 2>&1
  rc=$?
  if [ "$rc" = 3 ]; then
    echo "[runner] backed off (low RAM), waiting 90s" >> "$RUNLOG"; sleep 90
  else
    sleep 5
  fi
done
