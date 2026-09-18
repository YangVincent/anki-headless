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
# 5, not 2. The prune runs before every op, so KEEP=2 meant the next two runs would have
# deleted this session's only two pre-change snapshots -- the evidence a rollback or an
# audit depends on. At ~112MB each that costs about 560MB of 21GB free. The daily gzipped
# backups in /home/vincent/backups/anki cover longer history at 29MB each.
KEEP=5

# The backup is taken AFTER the bot stops and the lock clears, and with sqlite3 .backup
# rather than cp. The collection runs in WAL mode: cp copies only the main file, so a
# committed write still sitting in collection.anki2-wal is silently absent from the copy.
# Taking it first, while the bot was still writing, produced backups that rolled a
# committed suspend back to its pre-write state. A backup that can be stale is worse than
# no backup, because it is trusted.

# Declare the maintenance window BEFORE the bot stops.
#
# The bot owns the 30-second job that confirms cache.db against the collection, so while
# it is stopped `meta.checked_at` freezes and every strict consumer starts refusing after
# 15 minutes. A declared pause is not staleness. It EXPIRES, so a run that dies here
# cannot silence the check forever.
echo "[anki_op] declaring a cache pause"
"$PY" /home/vincent/anki-headless/anki_cache.py pause 3600 || \
  echo "[anki_op] WARNING: could not pause the cache (it may not exist yet)"

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

# Pull from AnkiWeb BEFORE the backup and BEFORE the op.
#
# The op is about to write card rows. A card row holds one value per card, so it cannot
# merge: if the study device holds answers that have not reached the server, the op's
# stale row wins the next sync and the review is destroyed. That happened 62 times
# between 2026-06-08 and 2026-09-18 -- resort_main_queue.py repositions every NEW card,
# so it overwrote exactly the cards Vincent had just started. The revlog survived each
# time, because revlog rows have unique ids and never conflict, which is how the damage
# was found and repaired (freq_data/repair_lost_scheduling.py).
#
# Pulling first cannot close the window completely: a phone can always hold an answer it
# has not uploaded. It does remove the case that caused every one of those 62 -- a device
# that HAS uploaded, and a local copy that never asked for the changes.
#
# Set ANKI_OP_NO_PULL=1 to skip it (offline, or a deliberate local-only run).
if [ "${ANKI_OP_NO_PULL:-0}" = "1" ]; then
  echo "[anki_op] pull SKIPPED (ANKI_OP_NO_PULL=1)"
else
  echo "[anki_op] pulling from AnkiWeb before the write"
  "$PY" - "$COL" <<'PYPULL'
import json, os, sys
from anki.collection import Collection
from anki.sync import SyncAuth
auth_file = os.path.expanduser("~/.anki_auth")
if not os.path.exists(auth_file):
    print("[anki_op] WARNING: ~/.anki_auth missing; no pull. A device review made since "
          "the last sync can still be overwritten by this op.")
    sys.exit(0)
col = Collection(sys.argv[1])
try:
    data = json.load(open(auth_file))
    auth = SyncAuth(); auth.hkey = data["hkey"]
    if data.get("endpoint"):
        auth.endpoint = data["endpoint"]
    res = col.sync_collection(auth, sync_media=False)
    if res.new_endpoint:
        data["endpoint"] = res.new_endpoint
        json.dump(data, open(auth_file, "w")); os.chmod(auth_file, 0o600)
    if res.required == 2:
        print("[anki_op] ERROR: AnkiWeb wants a FULL SYNC. Resolve it with `anki-cli sync` "
              "and decide which side wins BEFORE any script writes.")
        sys.exit(1)
    print(f"[anki_op] pull ok (status={res.required})")
finally:
    col.close()
PYPULL
  if [ $? -ne 0 ]; then
    [ "$BOT_UP" = 1 ] && pm2 start anki-bot >/dev/null 2>&1
    "$PY" /home/vincent/anki-headless/anki_cache.py unpause || true
    exit 1
  fi
fi

echo "[anki_op] backup -> $(basename "$BAK")"
"$PY" - "$COL" "$BAK" <<'PYBAK'
import sys, sqlite3
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
d = sqlite3.connect(dst)
s.backup(d)          # WAL-aware: writes a consistent, fully-checkpointed copy
d.close(); s.close()
PYBAK
if [ $? -ne 0 ] || [ ! -s "$BAK" ]; then
  echo "[anki_op] backup FAILED, aborting"
  rm -f "$BAK"
  [ "$BOT_UP" = 1 ] && pm2 start anki-bot >/dev/null 2>&1
  exit 1
fi

# Retention: keep only the KEEP newest .bak files (~112MB each). Files without the .bak
# suffix, such as collection.anki2.pre-reposition-*, are never pruned.
ls -1t "$ROOT"/backups/collection.anki2.*.bak 2>/dev/null | tail -n +$((KEEP + 1)) | while IFS= read -r old; do
  echo "[anki_op] pruning old backup -> $(basename "$old")"
  rm -f "$old"
done

echo "[anki_op] running: $SCRIPT $*"
"$PY" "$SCRIPT" "$@"
RC=$?

[ "$BOT_UP" = 1 ] && { echo "[anki_op] restarting anki-bot"; pm2 start anki-bot >/dev/null 2>&1; }

# The script just changed the collection, so the cache is behind. Rebuild it here rather
# than waiting up to 30 s, then clear the pause -- in that order, so no consumer can read
# an unpaused cache that is still stale.
echo "[anki_op] rebuilding the read cache"
"$PY" /home/vincent/anki-headless/anki_cache.py build || \
  echo "[anki_op] WARNING: cache rebuild failed; the bot's 30s job will retry"
"$PY" /home/vincent/anki-headless/anki_cache.py unpause || true

echo "[anki_op] done (op exit=$RC, backup=$(basename "$BAK"))"
exit $RC
