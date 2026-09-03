#!/usr/bin/env python3
"""Build the study set for one book out of what the collection already holds.

    book_deck.py <candidates.json> "<book>" [--screened <screened.json>] [--apply]

Generalised from shinian_deck.py, which did this for 《十年》 alone. The trilogy needs it
three times, and a copy per book is three places for the same bug.

WHY NOT A NEW DECK. decks.py declares the whole collection, and the 2026-08-19/09-01
consolidations went 26 -> 8 -> 5 on purpose; a subdeck per book would undo that. The
words mostly are not missing either. For 《黑暗森林》, of 407 words worth studying only 92
have no card at all: 261 sit queued in a live deck and 52 are parked in Archive. A naive
deck would create 315 duplicates.

So this does three things and reuses the canonical path for each:

  1. creates a ChineseVocabulary note for each word with no card, filed by ROLE into the
     new-words deck (never by literal name, never with col.decks.id(), which CREATES a
     deck bound to the wrong preset)
  2. calls bot.promote_to_vocab() for every word that already has a note -- the same
     function the Telegram wild-add uses. It moves the forward card to the front of its
     deck, unsuspends it, and routes the reverse and cloze cards to their gated decks.
  3. tags every note `book::<book>`, so the set is one search away and the dashboard
     draws it as a row

--screened takes the answers saved from the screening page (build_screen_page.py), whose
`known` list is the words the reader already reads without help. Those are dropped. The
page is the only thing that can make that call: 三体, 太阳系 and 美国 all sit high in the
frequency list with no card, and none of them is a word to study.

Usage:
    freq_data/book_deck.py freq_data/gen_santi/heianshenlin_words.json 黑暗森林 \\
        --screened freq_data/gen_santi/heianshenlin_screened.json
    bash freq_data/anki_op.sh heianshenlin-deck freq_data/book_deck.py \\
        freq_data/gen_santi/heianshenlin_words.json 黑暗森林 \\
        --screened freq_data/gen_santi/heianshenlin_screened.json --apply
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

#: Marks a note this script created without an example sentence.
NEEDS_SENTENCE = "needs::sentence"
NAMES = ROOT / "freq_data" / "gen_coldwindow" / "names_manual.json"


def tone_pinyin(word):
    from pypinyin import Style, pinyin
    return " ".join(p[0] for p in pinyin(word, style=Style.TONE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates")
    ap.add_argument("book")
    ap.add_argument("--screened")
    ap.add_argument("--db", default=str(ROOT / "collection.anki2"))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    tag = f"book::{args.book}"
    candidates = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
    manual = set(json.loads(NAMES.read_text(encoding="utf-8")).get(args.book, []))
    screened = set()
    if args.screened:
        screened = set(json.loads(
            Path(args.screened).read_text(encoding="utf-8")).get("known", []))

    words = [c for c in candidates if c["w"] not in manual and c["w"] not in screened]
    print(f"{len(candidates)} candidates - {len(manual)} hand-marked names "
          f"- {len(screened)} you already read -> {len(words)} words")

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
            for t in ("chinese", "claude", "mined", tag):
                note.add_tag(t)
            # A note with no example sentence is not finished. This script writes four
            # fields and cannot author a sentence, so it SAYS SO instead of leaving a
            # silent hole: 十年's first run created 54 sentence-less notes and nothing
            # recorded that, so they only surfaced weeks later in a full audit.
            # apply_sentences.py clears the tag when the sentence lands.
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
            if tag not in note.tags:
                note.add_tag(tag)
                col.update_note(note)
            tagged += 1

        # No col.save(): the modern backend commits on its own and the call warns
        # "saving is automatic". Inherited from shinian_deck.py, where it is equally
        # dead; copying it forward would have carried the warning into every book.
        after_cards, after_notes = col.card_count(), col.note_count()
        print(f"\nverify: notes {notes_before} -> {after_notes} "
              f"(+{after_notes - notes_before}, expected +{len(missing_note)})")
        print(f"verify: cards {cards_before} -> {after_cards} (+{after_cards - cards_before})")
        print(f"verify: notes carrying {tag}: {len(col.find_notes(f'tag:{tag}'))} "
              f"(want {tagged})")
        print(f"verify: notes marked {NEEDS_SENTENCE}: "
              f"{len(col.find_notes(f'tag:{NEEDS_SENTENCE}'))}")
        # The guard exists to catch cards moving where they were not meant to. A book
        # set DOES grow the new-words deck, by exactly (new notes + cards promoted out of
        # Archive), so print that arithmetic beside the delta instead of flagging every
        # run as suspicious. A bare "<-- CHANGED" that fires on every correct run is a
        # warning nobody reads.
        expected = len(missing_note) + promoted.get("moved_to_mined", 0)
        for name, before in guard.items():
            now = len(col.find_cards(f'deck:"{name}"'))
            delta = now - before
            if delta == 0:
                note_ = ""
            elif name == decks.NEW_WORDS_DECK and delta == expected:
                note_ = f"  (+{delta} = {len(missing_note)} new + " \
                        f"{promoted.get('moved_to_mined', 0)} promoted from Archive)"
            else:
                note_ = f"  <-- UNEXPECTED {delta:+d}"
            print(f"verify: deck {name} cards {before} -> {now}{note_}")
    finally:
        col.close()


if __name__ == "__main__":
    main()
