#!/usr/bin/env python3
"""Suspend the queued single-character cards for characters that are never words.

The HSK deck holds 1,082 single-character cards, 733 of which have never been shown.
400 of those are characters that essentially never stand alone in modern Chinese, and
274 of the 400 are one half of a two-character word whose other half is *also* queued as
its own card — 咳 and 嗽 are scheduled separately, but the word is 咳嗽. 乒 has no
meaning without 乓. A card asking for the meaning of half a word cannot be answered, and
these are already the worst-performing cards in the deck: single characters lapse 3+
times at twice the rate of words (15% vs 7%).

What this does and does not touch:
  * suspends only cards that are single characters, unsuspended, NEVER STUDIED, and whose
    standalone-word frequency is below the threshold. Nothing you have already learned is
    touched — those 170 studied character cards stay exactly as they are.
  * suspend, not delete. Every card keeps its history and its place; the tag makes the
    set trivially reversible (see --undo).
  * characters that genuinely are words (脱, 演, 降 …) stay in the queue.

  park_bound_chars.py                 # dry run
  park_bound_chars.py --apply         # via freq_data/anki_op.sh
  park_bound_chars.py --undo --apply  # put them all back
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path("/home/vincent/anki-headless")
COL = ROOT / "collection.anki2"
DECK = "HSK"
TAG = "parked::bound-character"
THRESHOLD = 4.0        # zipf standalone-word frequency; below this it is not a word
HANZI = re.compile(r"^[一-鿿]$")


def _sync(col):
    from anki.sync import SyncAuth
    cred = json.loads(Path("~/.anki_auth").expanduser().read_text())
    auth = SyncAuth()
    auth.hkey = cred["hkey"]
    if cred.get("endpoint"):
        auth.endpoint = cred["endpoint"]
    out = col.sync_collection(auth, sync_media=False)
    print("sync: " + {0: "nothing further to send", 1: "changes uploaded",
                      2: "FULL SYNC REQUIRED — resolve by hand"}
          .get(out.required, f"status {out.required}"))


def main():
    from anki.collection import Collection
    from wordfreq import zipf_frequency

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo", action="store_true", help="unsuspend everything tagged")
    ap.add_argument("--limit", type=int, help="only the first N due (default: all of them)")
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    ap.add_argument("--col", default=str(COL))
    a = ap.parse_args()
    if a.apply and a.col != str(COL):
        raise SystemExit("--apply only ever writes the real collection")

    col = Collection(a.col)
    try:
        if a.undo:
            ids = col.find_cards(f'tag:"{TAG}"')
            print(f"{len(ids)} cards tagged {TAG}")
            if a.apply:
                col.sched.unsuspend_cards(ids)
                for nid in col.find_notes(f'tag:"{TAG}"'):
                    note = col.get_note(nid)
                    note.remove_tag(TAG)
                    col.update_note(note)
                print("unsuspended and untagged.")
                _sync(col)
            else:
                print("(dry run)")
            return

        target, kept = [], 0
        for cid in col.find_cards(f'deck:"{DECK}"'):
            card = col.get_card(cid)
            word = card.note()["Simplified"]
            if not HANZI.match(word):
                continue
            if card.queue == -1 or card.reps > 0 or card.type != 0:
                continue                      # suspended already, or already studied
            if zipf_frequency(word, "zh") >= a.threshold:
                kept += 1
                continue
            target.append((card.due, cid, word))
        target.sort()
        if a.limit:
            target = target[:a.limit]

        studied_before = len(col.find_cards(f'deck:"{DECK}" -is:suspended -is:new'))
        active_before = len(col.find_cards(f'deck:"{DECK}" -is:suspended'))

        print(f"{len(target)} unseen single-character cards to park "
              f"(standalone frequency below {a.threshold})")
        print(f"{kept} unseen character cards left in the queue — those are real words")
        print("  first 30: " + " ".join(w for _, _, w in target[:30]))

        if not a.apply:
            print("\n(dry run — nothing written)")
            return

        ids = [cid for _, cid, _ in target]
        col.sched.suspend_cards(ids)
        for nid in {col.get_card(cid).nid for cid in ids}:
            note = col.get_note(nid)
            note.add_tag(TAG)
            col.update_note(note)

        studied_after = len(col.find_cards(f'deck:"{DECK}" -is:suspended -is:new'))
        active_after = len(col.find_cards(f'deck:"{DECK}" -is:suspended'))
        assert studied_after == studied_before, \
            f"studied cards changed: {studied_before} -> {studied_after}"
        assert active_before - active_after == len(ids), \
            f"expected {len(ids)} fewer active cards, got {active_before - active_after}"
        print(f"\nparked {len(ids)} cards. HSK active: {active_before} -> {active_after}, "
              f"studied cards untouched at {studied_after} ✓")
        print(f"reversible with: park_bound_chars.py --undo --apply   (tag {TAG})")
        _sync(col)
    finally:
        col.close()


if __name__ == "__main__":
    main()
