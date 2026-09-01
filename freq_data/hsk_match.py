#!/usr/bin/env python3
"""Make the HSK deck's active set match the HSK 3.0 word list, and collapse the sweep tags.

Successive sweeps (parked::bound-character, ::studied-character, ::unseen-character,
::not-hsk-word) each parked single-character cards under a different rule, so the deck's
state is the sediment of four policies. The rule now is one thing: a card is active if its
text is an HSK word.

  restore   suspended cards in the deck that ARE HSK words AND carry a sweep tag — those
            were parked by a rule that no longer applies (e.g. 害, an HSK-5 word, parked
            for being a single character).
  park      active single-character cards whose character is NOT in the HSK word list.
  untag     drop the sweep tags everywhere once the deck agrees with the list.

NOT touched, deliberately:
  * suspended HSK words with no sweep tag (or tagged leech) — suspended for a reason this
    script cannot see, so restoring them would undo an unknown decision.
  * multi-character non-HSK words. The scope is individual characters.
  * scheduling. suspend/unsuspend preserve due, interval, ease, reps and lapses, so the
    existing queue order is unchanged.

Removing the tags destroys the per-batch undo handles, so every change is recorded to
generated/hsk_match_undo.json (card id -> previous queue, note tags) first. --undo replays
that file exactly.

  hsk_match.py                 # dry run
  hsk_match.py --apply         # via freq_data/anki_op.sh
  hsk_match.py --undo --apply  # replay the recorded snapshot
"""
import sys
sys.path.insert(0, "/home/vincent/anki-headless")
import decks as deck_registry  # noqa: E402
import argparse
import json
import re
from pathlib import Path
from anki_common import sync as _sync

ROOT = Path("/home/vincent/anki-headless")
COL = ROOT / "collection.anki2"
UNDO = ROOT / "generated" / "hsk_match_undo.json"
# The HSK 3.0 word list, 10,960 words. Generated from hsk30_official.json, which is built
# from the official band IDs — see dong-chinese/server/scripts/build_hsk30_tsv.py.
HSK_TSV = Path("/home/vincent/chinese-projects/dong-chinese/server/app/data/hsk30.tsv")
# Real words that are NOT in HSK 3.0 (你好, 玩, 老虎, 数学, …). This sweep suspends cards it
# judges "not an HSK word", so parking one of these would be wrong: the user has a card for
# it and it is ordinary Chinese, it simply is not on the syllabus. The membership authority
# is therefore the UNION, which errs toward "is a word" — the safe direction for suspension.
#
# 2026-08-28: this used to point at hsk3_vocab.json, whose Level column is ~31% correct
# (see quarantine/README.md). Only membership was ever read from it here, so the fix was to
# strip the corrupt columns rather than drop the file. Levels come from HSK_TSV alone.
SUPPLEMENTARY_JSON = Path("/home/vincent/anki-headless/freq_data/supplementary_vocab.json")
DECK = deck_registry.RECOGNITION_DECKS[0]
SWEEP_TAGS = ["parked::bound-character", "parked::studied-character",
              "parked::unseen-character", "parked::not-hsk-word"]
HANZI = re.compile(r"^[一-鿿]$")


def hsk_words():
    out = set()
    for line in HSK_TSV.open(encoding="utf-8"):
        w, _, lv = line.rstrip("\n").partition("\t")
        lv = lv.split("\t")[-1] if "\t" in lv else lv
        if lv.isdigit():
            out.add(w)
    out.update(x["word"] for x in json.loads(SUPPLEMENTARY_JSON.read_text(encoding="utf-8")))
    return out



def main():
    from anki.collection import Collection

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo", action="store_true", help="replay hsk_match_undo.json")
    ap.add_argument("--deck", default=DECK)
    ap.add_argument("--col", default=str(COL))
    a = ap.parse_args()
    if a.apply and a.col != str(COL):
        raise SystemExit("--apply only ever writes the real collection")

    col = Collection(a.col)
    try:
        if a.undo:
            snap = json.loads(UNDO.read_text(encoding="utf-8"))
            resus = [int(c) for c, q in snap["queues"].items() if q == -1]
            reunsus = [int(c) for c, q in snap["queues"].items() if q != -1]
            print(f"replaying {UNDO.name}: re-suspend {len(resus)}, re-unsuspend {len(reunsus)}, "
                  f"restore tags on {len(snap['tags'])} notes")
            if not a.apply:
                print("(dry run)")
                return
            if resus:
                col.sched.suspend_cards(resus)
            if reunsus:
                col.sched.unsuspend_cards(reunsus)
            for nid, tags in snap["tags"].items():
                note = col.get_note(int(nid))
                note.tags = tags
                col.update_note(note)
            print("undone.")
            _sync(col)
            return

        HSK = hsk_words()
        decks = {r[0]: r[1].replace("\x1f", "::") for r in col.db.all("select id, name from decks")}
        rows = col.db.all("select c.id, c.queue, c.did, n.id, n.sfld, n.tags "
                          "from cards c join notes n on n.id = c.nid")

        restore, park, skipped = [], [], 0
        for cid, q, did, nid, sfld, tags in rows:
            if decks.get(did, "").split("::")[0] != a.deck:
                continue
            s = str(sfld or "").strip()
            tagged = any(t in (tags or "") for t in SWEEP_TAGS)
            if q == -1 and s in HSK:
                if tagged:
                    restore.append(cid)
                else:
                    skipped += 1              # suspended for a reason we cannot see
            elif q >= 0 and HANZI.match(s) and s not in HSK:
                park.append(cid)

        # tag cleanup is global: the sweeps tagged notes whose cards live in other decks too
        tagged_notes = set()
        for t in SWEEP_TAGS:
            tagged_notes.update(col.find_notes(f'tag:"{t}"'))

        print(f"deck {a.deck!r} vs the HSK 3.0 word list")
        print(f"  restore (HSK word, parked by an old sweep) : {len(restore):>5}")
        print(f"  park    (single char, not an HSK word)     : {len(park):>5}")
        print(f"  left alone (suspended, no sweep tag)       : {skipped:>5}")
        print(f"  sweep tags to drop, across all decks       : {len(tagged_notes):>5} notes")

        if not a.apply:
            print("\n(dry run — nothing written)")
            return

        UNDO.parent.mkdir(parents=True, exist_ok=True)
        snap = {"queues": {}, "tags": {}}
        for cid in restore + park:
            snap["queues"][str(cid)] = col.get_card(cid).queue
        for nid in tagged_notes:
            snap["tags"][str(nid)] = col.get_note(nid).tags
        UNDO.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
        print(f"\nundo snapshot -> {UNDO}")

        if restore:
            col.sched.unsuspend_cards(restore)
        if park:
            col.sched.suspend_cards(park)
        for nid in tagged_notes:
            note = col.get_note(nid)
            for t in SWEEP_TAGS:
                note.remove_tag(t)
            col.update_note(note)

        # verify: every active card in the deck is an HSK word or a multi-char non-HSK word,
        # and no active single character sits outside the list
        bad = [cid for cid, q, did, nid, sfld, tags in col.db.all(
            "select c.id, c.queue, c.did, n.id, n.sfld, n.tags from cards c "
            "join notes n on n.id = c.nid")
            if decks.get(did, "").split("::")[0] == a.deck and q >= 0
            and HANZI.match(str(sfld or "").strip()) and str(sfld or "").strip() not in HSK]
        assert not bad, f"{len(bad)} active non-HSK single characters remain"
        left = sum(1 for t in SWEEP_TAGS for _ in col.find_notes(f'tag:"{t}"'))
        assert left == 0, f"{left} notes still carry a sweep tag"
        print(f"restored {len(restore)}, parked {len(park)}, dropped tags on "
              f"{len(tagged_notes)} notes. no active non-HSK single characters remain ✓")
        _sync(col)
    finally:
        col.close()


if __name__ == "__main__":
    main()
