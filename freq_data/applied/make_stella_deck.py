#!/usr/bin/env python3
"""Create the `Stella An` deck for words mined from 安争鸣's videos.

DECK-LEVEL LIMIT, NOT A NEW PRESET. Creating a fresh preset ships Anki's stock defaults
(new.order RANDOM, empty FSRS params, autoplay on) instead of the trained ones, and that
has broken this collection before. This deep-copies the preset the deck lands on and sets
a per-deck `newLimit` instead -- the same mechanism used for HSK7-9 and Mined.

Run through freq_data/anki_op.sh. Dry-run by default; pass --apply to write.
"""
import argparse
import sys

from anki.collection import Collection

COL = "/home/vincent/anki-headless/collection.anki2"
DECK = "Stella An"
PER_DAY = 3


def snapshot(col):
    out = {}
    for d in col.decks.all_names_and_ids():
        deck = col.decks.get(d.id)
        if not deck or deck.get("dyn"):
            continue
        cfg = col.decks.config_dict_for_deck_id(d.id)
        out[d.name] = (cfg["id"], cfg["new"]["perDay"], deck.get("newLimit"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    col = Collection(COL)
    try:
        before = snapshot(col)
        if DECK in before:
            print(f"{DECK} already exists: {before[DECK]}")
        print(f"decks now: {len(before)}")

        if not args.apply:
            print(f"\nwould create {DECK!r} with a deck-level newLimit of {PER_DAY}")
            print("DRY-RUN (pass --apply)")
            return

        did = col.decks.id(DECK)          # creates it, on the Default preset
        deck = col.decks.get(did)
        deck["newLimit"] = PER_DAY
        col.decks.save(deck)

        after = snapshot(col)
        cfg = col.decks.config_dict_for_deck_id(did)
        print(f"\ncreated {DECK!r}")
        print(f"   preset      : {cfg['id']} {cfg['name']!r} (perDay {cfg['new']['perDay']})")
        print(f"   deck newLimit: {after[DECK][2]}  -> effective {PER_DAY}/day")

        # nothing else may have moved
        changed = [k for k in before if before[k] != after.get(k)]
        assert changed == [], f"other decks changed: {changed}"
        sharers = [k for k, v in after.items() if v[0] == cfg["id"] and k != DECK]
        print(f"   decks sharing that preset: {sharers}")
        print("\nVERIFIED: no existing deck's limits changed.")
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
