#!/usr/bin/env bash
#
# Daily Anki maintenance. Replaces cloze_gate_cron.sh (2026-08-19).
#
# The gate no longer runs here. bot.py applies the identical rule in-process every 5
# minutes via periodic_sync, and the rule is idempotent, so a daily run found nothing to
# do. What the old cron actually provided, by accident, was the collection's only regular
# backup — and it took that backup with `cp` BEFORE stopping the bot, so a write still in
# the WAL was silently missing from it.
#
# This does the two things that are genuinely daily, and neither needs the bot stopped:
#   1. An online, WAL-safe, verified, compressed backup with 14-day retention.
#   2. A read-only check that the gate's invariants still hold. Exits non-zero if not.
#
set -uo pipefail
ROOT=/home/vincent/anki-headless
COL="$ROOT/collection.anki2"
PY="$ROOT/.venv/bin/python"
BACKUP_DIR=/home/vincent/backups/anki
RETENTION_DAYS=14

mkdir -p "$BACKUP_DIR"
TS=$(date +%Y%m%d-%H%M%S)
TARGET="$BACKUP_DIR/anki-$TS.db"

# mode=ro so this can never take a write lock from the running bot. sqlite3's .backup is
# the online-backup API: it is WAL-aware and produces a consistent, checkpointed copy.
/usr/bin/python3.12 - "$COL" "$TARGET" <<'PYBAK'
import sys, sqlite3
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
d = sqlite3.connect(dst)
s.backup(d)
d.close(); s.close()
PYBAK
RC=$?

if [ $RC -ne 0 ] || [ ! -s "$TARGET" ]; then
  echo "$(date -Iseconds) anki_daily: BACKUP FAILED" >&2
  rm -f "$TARGET"
else
  # NOT PRAGMA quick_check: this collection uses Anki's custom `unicase` collation, which
  # the sqlite3 CLI does not have, so quick_check aborts with "no such collation sequence"
  # on every healthy file. Compare row counts against the source instead — that proves the
  # copy is both readable and complete.
  COUNT_SQL="SELECT (SELECT count(*) FROM cards)||'/'||(SELECT count(*) FROM notes)||'/'||(SELECT count(*) FROM revlog);"
  SRC_COUNTS=$(sqlite3 "file:$COL?mode=ro" "$COUNT_SQL" 2>/dev/null)
  DST_COUNTS=$(sqlite3 "$TARGET" "$COUNT_SQL" 2>/dev/null)
  if [ -n "$DST_COUNTS" ] && [ "$SRC_COUNTS" = "$DST_COUNTS" ]; then
    gzip -6 "$TARGET"
    find "$BACKUP_DIR" -name 'anki-*.db.gz' -mtime "+$RETENTION_DAYS" -print -delete
    echo "$(date -Iseconds) anki_daily: backup $(du -h "$TARGET.gz" | cut -f1) -> $TARGET.gz (cards/notes/revlog $DST_COUNTS)"
  else
    echo "$(date -Iseconds) anki_daily: $TARGET incomplete (source $SRC_COUNTS, copy ${DST_COUNTS:-unreadable})" >&2
    rm -f "$TARGET"
  fi
fi

echo "$(date -Iseconds) anki_daily: gate verify"
"$PY" "$ROOT/freq_data/template_gate.py" --verify
VRC=$?
[ $VRC -ne 0 ] && echo "$(date -Iseconds) anki_daily: GATE VERIFY FAILED (exit $VRC)" >&2
exit $VRC
