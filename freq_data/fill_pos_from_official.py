#!/usr/bin/env python3
"""Fill PartOfSpeech ONLY where the official HSK 3.0 list supplies it.

503 mined notes have an empty PartOfSpeech against 22% elsewhere, and the field IS
rendered -- it shows on Hanzi-English, the card Vincent actually studies. But only 39 of
those words appear in hsk30_official.json.

THE OTHER 464 ARE LEFT EMPTY ON PURPOSE. The taxonomy in use is HSK 3.0's own -- "verb
with nominal function", "adjective as adverbial", "verb, noun" -- which no general POS
tagger reproduces. Inferring 464 values would put a plausible wrong label on the front of
a card, and a wrong label is worse than a blank one: the blank is visibly missing, the
label is silently misleading. lint_cards.py records the same lesson from the other
direction, where three "defects" turned out to be the collection's own norm.

Usage: bash freq_data/anki_op.sh fill-pos freq_data/fill_pos_from_official.py --apply
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path("/home/vincent/anki-headless")
sys.path.insert(0, str(ROOT))

import anki.collection  # noqa: E402,F401
from anki.collection import Collection  # noqa: E402

import decks  # noqa: E402


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "collection.anki2"))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    official = {e["word"]: (e.get("pos") or "").strip()
                for e in json.loads((ROOT / "freq_data/hsk30_official.json")
                                    .read_text(encoding="utf-8"))}
    col = Collection(args.db)
    try:
        model = col.models.by_name("ChineseVocabulary")
        IX = {f["name"]: i for i, f in enumerate(model["flds"])}
        archived = set(decks.deck_ids_for(col, decks.ARCHIVE))
        filled, skipped_no_data = [], 0

        for nid in col.find_notes('"note:ChineseVocabulary" PartOfSpeech:'):
            dids = {c.did for c in col.get_note(nid).cards()}
            if not (dids - archived):
                continue                                  # archived only
            note = col.get_note(nid)
            word = strip_html(note.fields[0])
            pos = official.get(word, "")
            if not pos:
                skipped_no_data += 1
                continue
            if args.apply:
                note.fields[IX["PartOfSpeech"]] = pos
                col.update_note(note)
            filled.append((word, pos))

        print(f"live notes with an empty PartOfSpeech: {len(filled) + skipped_no_data}")
        print(f"  fillable from hsk30_official.json: {len(filled)}")
        print(f"  left empty (not in the official list): {skipped_no_data}")
        for w, p in filled[:10]:
            print(f"    {w:<10}{p}")
        if not args.apply:
            print("\n(dry run; nothing written)")
            return
        left = len(col.find_notes('"note:ChineseVocabulary" PartOfSpeech:'))
        print(f"\nverify: notes still missing PartOfSpeech: {left}")
        bad = [w for w, p in filled
               if strip_html(col.get_note(col.find_notes(f'"Simplified:{w}"')[0])
                             .fields[IX["PartOfSpeech"]]) != p]
        print(f"verify: fills that did not take: {len(bad)} (want 0)")
    finally:
        col.close()


if __name__ == "__main__":
    main()
