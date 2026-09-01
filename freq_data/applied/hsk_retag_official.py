#!/usr/bin/env python3
"""RETIRED 2026-09-01. It names a deck that no longer exists: `HSK`, `HSK7-9`,
`non-HSK` and `Mined` all became `Main` that day. Kept as a record of what was done
to the collection, not as a tool. Re-running it would resolve nothing and report
success -- the exact failure freq_data/README.md warns about.

Re-tag HSK::HSKn on the HSK / HSK7-9 decks from the official HSK 3.0 list.

The old tags came from hsk3_vocab.json, whose Level column was desynchronised by the PDF
parse that produced it (see build_hsk30_official.py). Restricted to HSK 1-6 it had the
right level for 31% of words, so the tags — and therefore the new-card ORDER, which
resort_hsk_queue.py sorts by level — were wrong for most of the deck.

Tags win over the vocab file in resort_hsk_queue.level_of(), so both have to move together:
run this, then re-run resort_hsk_queue.py (which now reads hsk30_official.json).

A word in more than one band is tagged with the LOWEST — where you first meet it.
A card whose word is not in HSK 3.0 at all keeps no HSK::HSKn tag: most are single
characters, which the sorter positions by first-use rather than by level, so an invented
level on them is noise that can only mislead.

Usage: bash freq_data/anki_op.sh hsk-retag freq_data/hsk_retag_official.py --apply
"""
import argparse
import collections
import json
import re

from anki.collection import Collection

ROOT = "/home/vincent/anki-headless"
DECKS = ("HSK", "HSK7-9")
TAG = re.compile(r"^HSK::HSK([1-6]|7-9)$")


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
        cc_id = col.models.by_name("ChineseCharacters")["id"]
        moves = collections.Counter()
        added = removed = same = 0
        absent_char = absent_word = 0
        seen = set()
        for dname in DECKS:
            did = col.decks.id_for_name(dname)
            if did is None:
                continue
            # every card, not just ord=0: a note whose ord=0 card is archived elsewhere can
            # still have its ord=1 (English-Speaking) card living here, and scoping to ord=0
            # leaves those carrying the old wrong tag
            for nid, in col.db.all("SELECT DISTINCT nid FROM cards WHERE did=?", did):
                note = col.get_note(nid)
                if note.id in seen:
                    continue
                seen.add(note.id)
                word = strip_html(note.fields[0])
                cur = next((m.group(1) for t in note.tags for m in [TAG.match(t)] if m), None)
                want = official.get(word)

                if want is None:
                    if note.note_type()["id"] == cc_id:
                        absent_char += 1
                    else:
                        absent_word += 1
                    if cur is not None:
                        removed += 1
                        if args.apply:
                            note.remove_tag(f"HSK::HSK{cur}")
                            col.update_note(note)
                    continue

                if cur == want:
                    same += 1
                    continue
                if cur is None:
                    added += 1
                else:
                    moves[(cur, want)] += 1
                if args.apply:
                    if cur is not None:
                        note.remove_tag(f"HSK::HSK{cur}")
                    note.add_tag(f"HSK::HSK{want}")
                    col.update_note(note)

        print(f"already correct: {same}")
        print(f"tag changed:     {sum(moves.values())}")
        print(f"tag added:       {added}")
        print(f"bogus tag removed (word not in HSK 3.0): {removed}")
        print(f"not in HSK 3.0 — single characters: {absent_char}, words: {absent_word}")
        print("\nlargest moves:")
        for (a, b), n in moves.most_common(10):
            print(f"  HSK{a} -> HSK{b}: {n}")

        if args.apply:
            col.tags.clear_unused_tags()
            wrong = 0
            for dname in DECKS:
                did = col.decks.id_for_name(dname)
                for nid, in col.db.all("SELECT DISTINCT nid FROM cards WHERE did=?", did):
                    n = col.get_note(nid)
                    w = strip_html(n.fields[0])
                    cur = next((m.group(1) for t in n.tags for m in [TAG.match(t)] if m), None)
                    if cur != official.get(w):
                        wrong += 1
            print(f"\nverify: cards whose tag still disagrees with the official list: {wrong} (want 0)")
        else:
            print("\nDRY-RUN — nothing written.")
    finally:
        col.close()


if __name__ == "__main__":
    main()
