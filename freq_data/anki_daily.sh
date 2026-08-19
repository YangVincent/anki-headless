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

BACKUP_OK=0
if [ $RC -ne 0 ] || [ ! -s "$TARGET" ]; then
  echo "$(date -Iseconds) anki_daily: BACKUP FAILED" >&2
  rm -f "$TARGET" "$TARGET-wal" "$TARGET-shm"
else
  # NOT PRAGMA quick_check: this collection uses Anki's custom `unicase` collation, which
  # the sqlite3 CLI does not have, so quick_check aborts with "no such collation sequence"
  # on every healthy file. Compare row counts against the source instead — that proves the
  # copy is both readable and complete.
  # Counts for the DATA tables and the SCHEMA tables. Counting only cards, notes and
  # revlog accepted a copy with every notetype, template, field and deck row deleted —
  # Anki opens that file and reports 258,959 cards and 0 note types.
  #
  # Run in Python, not the sqlite3 CLI: `decks` and `notetypes` carry a UNIQUE index on
  # a column with Anki's custom `unicase` collation, so a bare `count(*)` over them fails
  # with "no such collation sequence" in any client that has not registered it. Adding
  # those two tables to a CLI query silently turned this check into one that always
  # failed, which the first real run caught.
  COUNTS=$(/usr/bin/python3.12 - "$COL" "$TARGET" <<'PYCOUNT'
import sqlite3, sys
TABLES = ("cards", "notes", "revlog", "notetypes", "templates", "fields", "decks", "col")
def counts(path, ro):
    uri = f"file:{path}?mode=ro" if ro else path
    con = sqlite3.connect(uri, uri=True)
    con.create_collation("unicase", lambda a, b: (a > b) - (a < b))
    try:
        return "/".join(str(con.execute(f"select count(*) from {t}").fetchone()[0])
                        for t in TABLES)
    finally:
        con.close()
try:
    print(counts(sys.argv[1], True)); print(counts(sys.argv[2], False))
except Exception as e:
    print("ERROR"); print(str(e).replace("\n", " "))
PYCOUNT
)
  SRC_COUNTS=$(echo "$COUNTS" | sed -n 1p)
  DST_COUNTS=$(echo "$COUNTS" | sed -n 2p)
  if [ "$SRC_COUNTS" != "ERROR" ] && [ -n "$DST_COUNTS" ] && [ "$SRC_COUNTS" = "$DST_COUNTS" ]; then
    gzip -6 "$TARGET"
    find "$BACKUP_DIR" -name 'anki-*.db.gz' -mtime "+$RETENTION_DAYS" -print -delete
    echo "$(date -Iseconds) anki_daily: backup $(du -h "$TARGET.gz" | cut -f1) -> $TARGET.gz ($DST_COUNTS)"
    BACKUP_OK=1
  else
    echo "$(date -Iseconds) anki_daily: $TARGET incomplete (source $SRC_COUNTS, copy ${DST_COUNTS:-unreadable})" >&2
    # -wal/-shm too: the verification read reopens the WAL-mode copy, and deleting only
    # the .db left orphan pairs that the retention find never prunes.
    rm -f "$TARGET" "$TARGET-wal" "$TARGET-shm"
  fi
fi

echo "$(date -Iseconds) anki_daily: gate verify"
"$PY" "$ROOT/freq_data/template_gate.py" --verify
VRC=$?
[ $VRC -ne 0 ] && echo "$(date -Iseconds) anki_daily: GATE VERIFY FAILED (exit $VRC)" >&2
# The BACKUP result reaches the exit code too. It did not: a failed backup printed one
# stderr line and the script still exited 0, so cron reported success while the
# collection's only regular backup silently stopped for as long as the fault lasted.
if [ "$BACKUP_OK" != 1 ]; then
  echo "$(date -Iseconds) anki_daily: exiting non-zero because the BACKUP failed" >&2
  exit 1
fi
exit $VRC
