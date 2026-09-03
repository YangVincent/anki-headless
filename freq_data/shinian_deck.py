#!/usr/bin/env python3
"""Build the study set for 《十年》 out of what the collection already holds.

WHY NOT A NEW DECK. The 2026-08-19 consolidation folded `Mined::十日终焉` into `Mined`
and decks.py now declares the whole collection; a new subdeck would undo that. And the
words mostly are not missing: of 208 words worth studying, 149 already sit queued in a
live deck and 15 are parked in the Archive. Only 46 have no card at all. A naive deck
would create 162 duplicates.

So this does three things and reuses the canonical paths for each:

  1. creates a ChineseVocabulary note for each word with no card, filed by ROLE into the
     new-words deck (never by literal name, never with col.decks.id(), which CREATES a
     deck bound to the wrong preset)
  2. calls bot.promote_to_vocab() for every word that already has a note — the same
     function the Telegram wild-add uses. It moves the forward card to the front of its
     deck, unsuspends it, and routes the reverse and cloze cards to their gated decks.
  3. tags every note `book::十年`, so the set is one search away

The words come from the screening page: Vincent marked the 185 he already reads, and
those are excluded. Names he left unmarked are in gen_coldwindow/names_manual.json.

Usage: bash freq_data/anki_op.sh shinian-deck freq_data/shinian_deck.py --apply
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path("/home/vincent/anki-headless")
sys.path.insert(0, str(ROOT))

from anki.collection import Collection  # noqa: E402

import bot  # noqa: E402
import decks  # noqa: E402

BOOK = "十年"
TAG = f"book::{BOOK}"
#: Marks a note this script created without an example sentence.
NEEDS_SENTENCE = "needs::sentence"
GEN = ROOT / "freq_data" / "gen_coldwindow"


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def tone_pinyin(word):
    from pypinyin import Style, pinyin
    return " ".join(p[0] for p in pinyin(word, style=Style.TONE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "collection.anki2"))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    candidates = json.loads((GEN / "shinian_deck_candidates.json").read_text(encoding="utf-8"))
    manual = set(json.loads((GEN / "names_manual.json").read_text(encoding="utf-8")).get(BOOK, []))
    words = [c for c in candidates if c["w"] not in manual]
    print(f"{len(candidates)} candidates, {len(manual)} hand-marked names removed "
          f"-> {len(words)} words")

    from opencc import OpenCC
    cc = OpenCC("s2tw")
    col = Collection(args.db)
    try:
        cards_before, notes_before = col.card_count(), col.note_count()
        model = col.models.by_name("ChineseVocabulary")
        IX = {f["name"]: i for i, f in enumerate(model["flds"])}
        mined_did = decks.new_words_deck_id(col)
        guard = {name: len(col.find_cards(f'deck:"{name}"'))
                 for name in decks.RECOGNITION_DECKS}

        existing, created, missing_note = [], [], []
        for c in words:
            word = c["w"]
            nids = [n for n in col.find_notes(f'"Simplified:{word}"')
                    if col.get_note(n).note_type()["name"] == bot.CHINESE_VOCAB_NOTETYPE]
            if nids:
                existing.extend(nids)
                continue
            note = col.new_note(model)
            note.fields[IX["Simplified"]] = word
            note.fields[IX["Pinyin"]] = tone_pinyin(word)
            note.fields[IX["Meaning"]] = c.get("m", "")
            note.fields[IX["Traditional"]] = cc.convert(word)
            for t in ("chinese", "claude", "mined", TAG):
                note.add_tag(t)
            # A note with no example sentence is not finished. This script writes four
            # fields and cannot author a sentence, so it SAYS SO instead of leaving a
            # silent hole: the first run created 54 sentence-less notes and nothing
            # recorded that, so they only surfaced when the whole collection was audited
            # weeks later. `needs::sentence` makes them one search away, and
            # freq_data/apply_sentences.py clears it when the sentence lands.
            note.add_tag(NEEDS_SENTENCE)
            if args.apply:
                col.add_note(note, mined_did)
                created.append(note.id)
            missing_note.append(word)

        print(f"  notes that already exist: {len(existing)}")
        print(f"  notes to create:          {len(missing_note)}")
        if missing_note[:8]:
            print("    e.g. " + " ".join(missing_note[:8]))

        if not args.apply:
            print("\n(dry run; pass --apply to write)")
            return

        promoted = bot.promote_to_vocab(col, existing + created)
        print(f"  promote_to_vocab: {promoted}")

        tagged = 0
        for nid in set(existing + created):
            note = col.get_note(nid)
            if TAG not in note.tags:
                note.add_tag(TAG)
                col.update_note(note)
            tagged += 1

        col.save()
        after_cards, after_notes = col.card_count(), col.note_count()
        print(f"\nverify: notes {notes_before} -> {after_notes} "
              f"(+{after_notes - notes_before}, expected +{len(missing_note)})")
        print(f"verify: cards {cards_before} -> {after_cards} (+{after_cards - cards_before})")
        print(f"verify: notes carrying {TAG}: {len(col.find_notes(f'tag:{TAG}'))} "
              f"(want {tagged})")
        print(f"verify: notes marked {NEEDS_SENTENCE}: "
              f"{len(col.find_notes(f'tag:{NEEDS_SENTENCE}'))}")
        for name, before in guard.items():
            now = len(col.find_cards(f'deck:"{name}"'))
            flag = "" if now == before else "  <-- CHANGED"
            print(f"verify: deck {name} cards {before} -> {now}{flag}")
    finally:
        col.close()


if __name__ == "__main__":
    main()
