"""File every HSK word in the deck matching its official band: 1-6 -> HSK, 7-9 -> HSK7-9.

Left over from the corrupted hsk3_vocab.json: 1,130 words sit in the wrong deck for their
real level. 817 HSK 7-9 words are in the HSK deck and 313 words of HSK 1-6 are in HSK7-9,
because whatever placed them believed the broken levels. The two decks have different
new/day limits (25 vs 10), so this is not cosmetic — it decides how fast each band is
introduced.

Moving a card between decks preserves its scheduling; only the deck's daily limits and
preset change. Studied cards move too (82 of them), because the point of the split is which
band a word belongs to, and that does not stop being true once you have seen it.

Usage: bash freq_data/anki_op.sh hsk-split freq_data/hsk_split_by_level.py --apply
"""
import argparse
import collections
import json
import re

from anki.collection import Collection

ROOT = "/home/vincent/anki-headless"
RANK = {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7-9": 7}


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    official = {e["word"]: e["level"]
                for e in json.load(open(f"{ROOT}/freq_data/hsk30_official.json"))}
    col = Collection(args.db)
    try:
        hsk = col.decks.id_for_name("HSK")
        hsk79 = col.decks.id_for_name("HSK7-9")
        moves = collections.defaultdict(list)
        counts = collections.Counter()
        for did in (hsk, hsk79):
            for nid, in col.db.all("SELECT DISTINCT nid FROM cards WHERE did=?", did):
                note = col.get_note(nid)
                word = strip_html(note.fields[0])
                lvl = official.get(word)
                if lvl is None:
                    continue                      # characters and non-HSK words: not ours to file
                dest = hsk if RANK[lvl] <= 6 else hsk79
                if dest == did:
                    continue
                for c in note.cards():
                    if c.did == did:
                        moves[dest].append(c.id)
                        counts[("HSK" if did == hsk else "HSK7-9",
                                "HSK" if dest == hsk else "HSK7-9")] += 1

        for (a, b), n in counts.items():
            print(f"  {a} -> {b}: {n} cards")
        print(f"total cards to move: {sum(len(v) for v in moves.values())}")

        if args.apply:
            for dest, cids in moves.items():
                col.set_deck(cids, dest)
            wrong = 0
            for did, ok in ((hsk, lambda l: l <= 6), (hsk79, lambda l: l == 7)):
                for nid, in col.db.all("SELECT DISTINCT nid FROM cards WHERE did=?", did):
                    w = strip_html(col.get_note(nid).fields[0])
                    if w in official and not ok(RANK[official[w]]):
                        wrong += 1
            print(f"\nverify: words in the wrong deck for their level: {wrong} (want 0)")
        else:
            print("\nDRY-RUN — nothing written.")
    finally:
        col.close()


if __name__ == "__main__":
    main()
