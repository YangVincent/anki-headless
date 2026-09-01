#!/usr/bin/env python3
"""RETIRED 2026-09-01. It names a deck that no longer exists: `HSK`, `HSK7-9`,
`non-HSK` and `Mined` all became `Main` that day. Kept as a record of what was done
to the collection, not as a tool. Re-running it would resolve nothing and report
success -- the exact failure freq_data/README.md warns about.

Move words that are not in HSK 3.0 out of the HSK / HSK7-9 decks.

Every one of the 1,062 offenders is present in the old hsk3_vocab.json, which listed 1,146
words the official standard does not contain. The gap-filling scripts (hsk_gap_add.py,
hsk_gap_create.py, hsk_match.py) trusted that file, so the deck was populated with words
that were never HSK: the chengyu batch (各抒己见, 锲而不舍 — the official list has 430
four-character HSK 7-9 entries, just not these), old HSK 2.0 leftovers, and ordinary words
like 这个 / 欧洲 / 链接.

Character cards go too. They were scaffolding — resort_hsk_queue puts a character card just
before the first word that uses it — but a character that is not itself an HSK 3.0 entry is
not a word on the list, and the deck is meant to be the list. Characters that ARE HSK
entries (many single characters are) stay, and keep their position rule.

Cards with review history are LEFT ALONE. Moving a card you have already learned throws
away its scheduling to satisfy a filing rule, which is a bad trade; the point of the rule
is to control what gets introduced next, and a studied card is past that. Only never-seen
cards move.

Destination is the non-HSK deck, which already exists for exactly this: real vocabulary
that is not part of the HSK list. Nothing is deleted.

Usage: bash freq_data/anki_op.sh hsk-prune freq_data/hsk_prune_non_official.py --apply
"""
import argparse
import collections
import json
import re

from anki.collection import Collection

ROOT = "/home/vincent/anki-headless"
SOURCE_DECKS = ("HSK", "HSK7-9")
DEST = "non-HSK"


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    official = {e["word"] for e in json.load(open(f"{ROOT}/freq_data/hsk30_official.json"))}
    col = Collection(args.db)
    try:
        dest = col.decks.id_for_name(DEST)
        if dest is None:
            raise SystemExit(f"destination deck {DEST!r} not found")
        src = {col.decks.id_for_name(d) for d in SOURCE_DECKS} - {None}
        cc_id = col.models.by_name("ChineseCharacters")["id"]

        move, kept, dropped, seen = [], [], [], set()
        for did in src:
            for nid, in col.db.all("SELECT DISTINCT nid FROM cards WHERE did=?", did):
                if nid in seen:
                    continue
                seen.add(nid)
                note = col.get_note(nid)
                word = strip_html(note.fields[0])
                if word in official:
                    continue
                here = [c for c in note.cards() if c.did in src]
                kind = "char" if note.note_type()["id"] == cc_id else "word"
                if any(c.type != 0 for c in here):
                    kept.append((kind, word))
                else:
                    move.extend(c.id for c in here)
                    dropped.append((kind, word))

        kc = collections.Counter(k for k, _ in dropped)
        print(f"  keeping (already studied): {len(kept)}  "
              f"({sum(1 for k, _ in kept if k == 'word')} words, {sum(1 for k, _ in kept if k == 'char')} chars)")
        print(f"  moving to {DEST} (never seen): {len(move)} cards  "
              f"({kc['word']} words, {kc['char']} chars)")
        print(f"  kept: {' '.join(w for _, w in sorted(kept))}")

        if args.apply:
            col.set_deck(move, dest)
            left = 0
            for did in src:
                for nid, in col.db.all("SELECT DISTINCT nid FROM cards WHERE did=?", did):
                    n = col.get_note(nid)
                    w = strip_html(n.fields[0])
                    if w in official:
                        continue
                    here = [c for c in n.cards() if c.did in src]
                    if here and all(c.type == 0 for c in here):
                        left += 1
            print(f"\nverify: unseen non-HSK-3.0 words still in the HSK decks: {left} (want 0)")
            studied_left = sum(1 for did in src
                               for nid, in col.db.all("SELECT DISTINCT nid FROM cards WHERE did=?", did)
                               if strip_html(col.get_note(nid).fields[0]) not in official
                               and any(c.type != 0 for c in col.get_note(nid).cards() if c.did in src))
            print(f"verify: studied non-HSK-3.0 words retained: {studied_left} (want {len(kept)})")
        else:
            print("\nDRY-RUN — nothing written.")
    finally:
        col.close()


if __name__ == "__main__":
    main()
