#!/usr/bin/env bash
# Logs extraction progress to _progress_history.log every 15 min for ~9h.
ROOT=/home/vincent/anki-headless; OCR="$ROOT/OCR"; LOG="$ROOT/freq_data/ocr/_progress_history.log"
prev=0
for i in $(seq 1 36); do
  pages=$(cat "$ROOT"/freq_data/ocr/*.jsonl 2>/dev/null | wc -l)
  d=$((pages-prev)); prev=$pages
  rate=$(awk -v d=$d 'BEGIN{printf "%.1f", d/15}')
  w=$(ps -C python -o args= 2>/dev/null | grep -c 'extract_corpus.py --of 4')
  la=$(cut -d' ' -f1 /proc/loadavg)
  mem=$(awk '/MemAvailable/{printf "%.1fG",$2/1048576}' /proc/meminfo)
  disk=$(df -h / | awk 'NR==2{print $4}')
  echo "$(date '+%F %T') pages=$pages (+$d/15min=${rate}/min) workers=$w load=$la mem=$mem disk=$disk" >> "$LOG"
  sleep 900
done
