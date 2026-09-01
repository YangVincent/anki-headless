#!/usr/bin/env python3
"""RETIRED 2026-09-01. Its premise is gone: it deleted a mined character card only when
the same character had an active card OUTSIDE `Mined`, and `Mined` was merged into `Main`
that day, so there is no outside. The 10 cards it was written for were removed in June.

Delete the 10 mined single-character cards that duplicate an existing HSK character card.

Root cause was mine_shuihu.py's dedup only checking ChineseVocabulary-in-Vocab, so single
characters that already had a ChineseCharacters card in HSK got a duplicate mined vocab card
(tag 'mined shuihu', 2026-06-17). mine_shuihu.py is now fixed to skip these; this removes the
10 already created. All 10 mined copies are reps=0 (never studied), so deletion loses no
history; the HSK originals (canonical, and holding 聚/伤's study history) stay.

Safety: only deletes a note when (a) its front is one of the 10 chars, (b) it's the mined
ChineseVocabulary note, (c) the same char has ANOTHER active card outside Mined, and (d) the
mined card has reps == 0. Anything failing these is left alone and reported.

  delete_mined_dupes.py            # dry run
  delete_mined_dupes.py --apply    # via freq_data/anki_op.sh
"""
import argparse
from pathlib import Path

COL = Path("/home/vincent/anki-headless/collection.anki2")
CHARS = ["烧", "判", "肥", "毒", "藏", "沿", "拔", "扑", "聚", "伤"]


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
        cv = col.models.by_name("ChineseVocabulary")
        decks = {r[0]: r[1].replace("\x1f", "::") for r in col.db.all("select id, name from decks")}
        to_delete, skip = [], []
        for ch in CHARS:
            cards = col.db.all(
                "select c.id, c.did, c.reps, c.queue, n.id, n.mid "
                "from cards c join notes n on n.id = c.nid where n.sfld = ?", ch)
            mined = [(cid, did, reps, q, nid) for cid, did, reps, q, nid, mid in cards
                     if mid == cv["id"] and decks.get(did, "").split("::")[0] == "Mined"]
            other_active = [cid for cid, did, reps, q, nid, mid in cards
                            if decks.get(did, "").split("::")[0] != "Mined" and q >= 0]
            if len(mined) == 1 and other_active and mined[0][2] == 0:
                to_delete.append((ch, mined[0][4]))          # (char, note id)
            else:
                skip.append((ch, f"mined={len(mined)} other_active={len(other_active)} "
                                 f"reps={mined[0][2] if mined else '-'}"))

        print(f"{len(to_delete)} mined duplicate notes to delete:")
        for ch, nid in to_delete:
            print(f"    {ch}  (note {nid})")
        for ch, why in skip:
            print(f"  SKIP {ch}: {why}")
        if not a.apply:
            print("\n(dry run — nothing written)")
            return

        col.remove_notes([nid for _, nid in to_delete])
        # verify each char still has an active non-Mined card and no Mined dupe remains
        bad = []
        for ch, _ in to_delete:
            cards = col.db.all("select c.did, c.queue from cards c join notes n on n.id=c.nid where n.sfld=?", ch)
            active_other = any(decks.get(did, "").split("::")[0] != "Mined" and q >= 0 for did, q in cards)
            mined_left = any(decks.get(did, "").split("::")[0] == "Mined" for did, q in cards)
            if not active_other or mined_left:
                bad.append(ch)
        assert not bad, f"post-check failed for: {bad}"
        print(f"\ndeleted {len(to_delete)} notes; every char still has its HSK card ✓")
        from anki_common import sync
        sync(col)
    finally:
        col.close()


if __name__ == "__main__":
    main()
