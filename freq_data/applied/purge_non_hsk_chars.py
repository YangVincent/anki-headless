#!/usr/bin/env python3
"""Delete the 431 single-character leftovers in non-HSK.

purge_non_hsk.py iterated `col.models.nids(ChineseVocabulary)` only, so it never saw the
ChineseCharacters notes -- 玩, 邦, 怖, 署, 袭, 吁, 奴, 隶 -- and left 431 behind, which is
why its final assertion failed. Same trash, same decision, different notetype.

Verified before deleting: all 431 are one character, NONE is on the official HSK 3.0
list, NONE was ever studied, and 74 are already taught by Hanly.

Dry-run unless --apply. Run through freq_data/anki_op.sh.
"""
import argparse
import json

from anki.collection import Collection

COL = "/home/vincent/anki-headless/collection.anki2"
OFFICIAL = "/home/vincent/anki-headless/freq_data/hsk30_official.json"
SRC = "non-HSK"
STUDIED = ("HSK", "Mined", "Stella An")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    official = {x["word"] for x in json.load(open(OFFICIAL, encoding="utf-8"))}
    col = Collection(COL)
    try:
        src = col.decks.id_for_name(SRC)
        assert src, f"no deck {SRC!r}"
        studied = {col.decks.id_for_name(d) for d in STUDIED} - {None}

        nids = col.db.list("SELECT DISTINCT nid FROM cards WHERE did=?", src)
        drop, spare = [], []
        for nid in nids:
            n = col.get_note(nid)
            w = n.fields[0].strip()
            reps = col.db.scalar(
                "SELECT coalesce(sum(reps),0) FROM cards WHERE nid=?", nid)
            in_studied = col.db.scalar(
                f"SELECT count(*) FROM cards WHERE nid=? AND did IN "
                f"({','.join('?' * len(studied))})", nid, *studied)
            if w in official or reps > 0 or in_studied:
                spare.append((w, "official" if w in official
                              else ("studied" if reps else "has a studied card")))
            else:
                drop.append(nid)

        cards = sum(col.db.scalar("SELECT count(*) FROM cards WHERE nid=?", n)
                    for n in drop)
        print(f"in {SRC}: {len(nids)} notes")
        print(f"delete: {len(drop)} notes / {cards} cards")
        print(f"spared: {len(spare)}")
        for w, why in spare[:12]:
            print(f"   keep {w}: {why}")
        if not args.apply:
            print("\nDRY-RUN (pass --apply)")
            return

        col.remove_notes(drop)
        left = col.db.scalar("SELECT count(*) FROM cards WHERE did=?", src)
        print(f"\n{SRC} now holds {left} card(s)")
        assert left == len(spare) or not spare and left == 0
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
