#!/usr/bin/env python3
"""Put the restored June/July cards back to new, as if they had never been reviewed.

repair_lost_scheduling.py rebuilt 62 cards from their revlog. That made 38 of them due
at once, three months late. Vincent kept the 12 he answered on 2026-09-18, kept 回头,
军人 and 逻辑, and asked for the other 47 to arrive at their curriculum position instead.

Each reset card:
  - goes back to new, with reps and lapses zeroed (`reset_counts=True`), so nothing in
    the scheduler remembers the old answers;
  - keeps its revlog, which is the audit trail and the evidence of the sync damage;
  - takes the tag `reset::2026-09-18`, so repair_lost_scheduling.py skips it. Without the
    tag that script would see `reps=0` next to real revlog rows and "repair" it again.

resort_main_queue.py then gives them their band-2 position: HSK level ascending, then
official list order.

Usage: bash freq_data/anki_op.sh reset-restored freq_data/reset_restored_to_new.py --apply
       bash freq_data/anki_op.sh resort-main freq_data/resort_main_queue.py --apply
"""
import sys, argparse, datetime, sqlite3

sys.path.insert(0, "/home/vincent/anki-headless")
from anki.collection import Collection

ROOT = "/home/vincent/anki-headless"
COL = f"{ROOT}/collection.anki2"
#: state of the collection immediately before repair_lost_scheduling.py ran
PRE_REPAIR = f"{ROOT}/backups/collection.anki2.20260918-160157.repair-sched.bak"
TAG = "reset::2026-09-18"
KEEP_WORDS = {"回头", "军人", "逻辑"}
TODAY = datetime.date(2026, 9, 18)


def repaired_card_ids():
    """The exact 62 cards repair_lost_scheduling.py touched, read from the backup taken
    just before it ran: reps=0 and type=0 while the revlog held real answers."""
    con = sqlite3.connect(f"file:{PRE_REPAIR}?immutable=1", uri=True)
    con.create_collation("unicase", lambda a, b: (a.lower() > b.lower()) - (a.lower() < b.lower()))
    try:
        return {r[0]: r[1] for r in con.execute(
            "SELECT c.id, n.sfld FROM cards c JOIN notes n ON n.id=c.nid "
            "WHERE c.reps=0 AND c.type=0 "
            "AND EXISTS (SELECT 1 FROM revlog r WHERE r.cid=c.id AND r.ease>0)")}
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--db", default=COL)
    args = ap.parse_args()

    repaired = repaired_card_ids()
    print(f"{len(repaired)} cards were repaired at 16:01")

    col = Collection(args.db)
    try:
        reset, kept = [], []
        for cid, word in repaired.items():
            last = col.db.scalar(
                "SELECT max(id) FROM revlog WHERE cid=? AND ease>0", cid)
            answered_today = (datetime.datetime.fromtimestamp(last / 1000).date() == TODAY)
            if answered_today or word in KEEP_WORDS:
                kept.append(word)
            else:
                reset.append((cid, word))
        print(f"  reset: {len(reset)}")
        print(f"  keep : {len(kept)}  {sorted(kept)}")
        print(f"\n{' '.join(w for _, w in sorted(reset, key=lambda x: x[1]))}")

        if not args.apply:
            print(f"\nDRY RUN — would reset {len(reset)}, write nothing")
            return 0

        for cid, _ in reset:
            note = col.get_note(col.get_card(cid).nid)
            if TAG not in note.tags:
                note.tags.append(TAG)
                col.update_note(note)
        col.sched.schedule_cards_as_new(
            [cid for cid, _ in reset], restore_position=False, reset_counts=True)

        bad = []
        for cid, word in reset:
            c = col.get_card(cid)
            if not (c.type == 0 and c.queue == 0 and c.reps == 0 and c.lapses == 0
                    and c.ivl == 0 and c.memory_state is None):
                bad.append((word, c.type, c.queue, c.reps, c.lapses, c.ivl,
                            c.memory_state is not None))
        print(f"\nreset {len(reset)} cards to new")
        print(f"VERIFY: {'every card is new, counts zeroed, no FSRS state'if not bad else f'PROBLEMS {bad}'}")
        tagged = col.db.scalar(
            f"SELECT count(*) FROM notes WHERE tags LIKE '%{TAG}%'")
        print(f"VERIFY: notes carrying {TAG}: {tagged} (want {len(reset)})")
        for word in sorted(kept):
            c = [x for x in col.find_cards(f'"deck:Main" "Simplified:{word}"')]
            print(f"  kept {word}: {[(col.get_card(i).type, col.get_card(i).queue) for i in c]}")
        return 0 if not bad else 1
    finally:
        col.close()


if __name__ == "__main__":
    sys.exit(main())
