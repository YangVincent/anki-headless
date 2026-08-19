#!/usr/bin/env python3
"""Unsuspend the 10 single-character HSK words that fell through every net.

Found 2026-07-28: suspended, untagged (so hsk_match left them), HSK words, not in Hanly,
and with NO active card anywhere — so nothing was teaching them, unlike the 102 suspended
HSK words that are just duplicates of an active card. All single characters, HSK 4-7:

  窗(4) 池(5) 晾(6) 唯 抵 攻 旬 枕 概 麻 (all 7-9 band)

Targets ONLY each character's card in a studied deck (HSK/HSK7-9/Mined/non-HSK/Vocab Cloze),
never the Hidden::Archive duplicate copies. Tags them so this is reversible.

  reinstate_stragglers.py            # dry run
  reinstate_stragglers.py --apply    # via freq_data/anki_op.sh
  reinstate_stragglers.py --undo --apply
"""
import argparse
import json
from pathlib import Path
from anki_common import sync as _sync

ROOT = Path("/home/vincent/anki-headless")
COL = ROOT / "collection.anki2"
TAG = "reinstated::straggler-char"
CHARS = ["窗", "池", "晾", "唯", "抵", "攻", "旬", "枕", "概", "麻"]
STUDY = ("HSK", "HSK7-9", "Mined", "non-HSK", "Vocab Cloze")



def main():
    from anki.collection import Collection

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo", action="store_true")
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
                col.sched.suspend_cards(ids)
                for nid in col.find_notes(f'tag:"{TAG}"'):
                    note = col.get_note(nid)
                    note.remove_tag(TAG)
                    col.update_note(note)
                print("re-suspended and untagged.")
                _sync(col)
            else:
                print("(dry run)")
            return

        decks = {r[0]: r[1].replace("\x1f", "::") for r in col.db.all("select id, name from decks")}
        target = []
        for ch in CHARS:
            hits = col.db.all(
                "select c.id, c.did from cards c join notes n on n.id = c.nid "
                "where n.sfld = ? and c.queue = -1", ch)
            picked = [cid for cid, did in hits if decks.get(did, "").split("::")[0] in STUDY]
            if not picked:
                print(f"  !! {ch}: no suspended study-deck card found")
            for cid in picked:
                target.append((cid, ch, decks.get(col.get_card(cid).did)))

        print(f"{len(target)} cards to reinstate:")
        for cid, ch, deck in target:
            print(f"    {ch}  ({deck})")
        if not a.apply:
            print("\n(dry run — nothing written)")
            return

        ids = [cid for cid, _, _ in target]
        col.sched.unsuspend_cards(ids)
        for nid in {col.get_card(cid).nid for cid in ids}:
            note = col.get_note(nid)
            note.add_tag(TAG)
            col.update_note(note)
        still = [cid for cid in ids if col.get_card(cid).queue == -1]
        assert not still, f"{len(still)} still suspended"
        print(f"\nreinstated {len(ids)} ✓  (undo: reinstate_stragglers.py --undo --apply)")
        _sync(col)
    finally:
        col.close()


if __name__ == "__main__":
    main()
