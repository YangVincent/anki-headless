#!/usr/bin/env python3
"""One-off repair: move the never-studied character notes onto the right parked tag.

A bug in park_studied_chars.py (the apply path hardcoded the studied tag instead of the
mode-specific one) tagged the 36 never-shown cards parked by `--unseen` as
parked::studied-character. The SUSPENSIONS are correct; only the tag is wrong, which would
have made `--undo` unsuspend both batches together instead of independently.

Identifies the mistagged notes structurally rather than by a hardcoded id list: a note
tagged parked::studied-character whose cards have all never been shown (max reps == 0)
could only have come from the --unseen run.

  retag_unseen_chars.py            # dry run
  retag_unseen_chars.py --apply    # via freq_data/anki_op.sh
"""
import argparse
import json
from pathlib import Path
from anki_common import sync as _sync

ROOT = Path("/home/vincent/anki-headless")
COL = ROOT / "collection.anki2"
FROM_TAG = "parked::studied-character"
TO_TAG = "parked::unseen-character"



def main():
    from anki.collection import Collection

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--col", default=str(COL))
    a = ap.parse_args()
    if a.apply and a.col != str(COL):
        raise SystemExit("--apply only ever writes the real collection")

    col = Collection(a.col)
    try:
        rows = col.db.all(
            "select n.id, max(c.reps), sum(c.queue = -1), count(*) "
            "from notes n join cards c on c.nid = n.id "
            f"where n.tags like '%{FROM_TAG}%' group by n.id")
        move = [r for r in rows if r[1] == 0]
        keep = [r for r in rows if r[1] > 0]
        unsuspended = sum(r[3] - r[2] for r in move)

        print(f"{len(rows)} notes tagged {FROM_TAG}")
        print(f"  {len(keep)} have studied cards — correctly tagged, left alone")
        print(f"  {len(move)} have never been shown — moving to {TO_TAG}")
        print(f"  (their cards: {sum(r[2] for r in move)} suspended, {unsuspended} still active — "
              f"suspension state is NOT changed by this script)")

        if not a.apply:
            print("\n(dry run — nothing written)")
            return

        for nid, *_ in move:
            note = col.get_note(nid)
            note.remove_tag(FROM_TAG)
            note.add_tag(TO_TAG)
            col.update_note(note)

        after_from = len(col.find_notes(f'tag:"{FROM_TAG}"'))
        after_to = len(col.find_notes(f'tag:"{TO_TAG}"'))
        assert after_from == len(keep), f"{FROM_TAG}: expected {len(keep)}, got {after_from}"
        assert after_to == len(move), f"{TO_TAG}: expected {len(move)}, got {after_to}"
        print(f"\nretagged. {FROM_TAG}: {after_from}   {TO_TAG}: {after_to} ✓")
        _sync(col)
    finally:
        col.close()


if __name__ == "__main__":
    main()
