#!/usr/bin/env python3
"""Delete every filtered deck, returning its borrowed cards to their home decks.

A filtered deck holds cards on loan: `did` is the filtered deck, `odid` the real one.
Deleting it must send every card home, so this verifies that rather than trusting it.

Deletes ONLY decks with the `dyn` flag set, and prints each one before removing it. A
normal deck deleted by mistake takes its cards with it; a filtered deck cannot.

Usage: bash freq_data/anki_op.sh clear-filtered freq_data/clear_filtered_decks.py --apply
"""
import argparse
import sys
from pathlib import Path

ROOT = Path("/home/vincent/anki-headless")
sys.path.insert(0, str(ROOT))

import anki.collection  # noqa: E402,F401
from anki.collection import Collection  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "collection.anki2"))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    col = Collection(args.db)
    try:
        on_loan = col.db.scalar("select count(*) from cards where odid != 0")
        dyn = [(d.id, d.name) for d in col.decks.all_names_and_ids()
               if col.decks.is_filtered(d.id)]
        print(f"filtered decks: {len(dyn)}   cards on loan: {on_loan}")
        for did, name in dyn:
            held = col.db.scalar("select count(*) from cards where did=?", did)
            print(f"  {name!r} (id {did}) holds {held} cards")
        if not dyn:
            print("nothing to do")
            return
        if not args.apply:
            print("\n(dry run; pass --apply to delete)")
            return

        homes = dict(col.db.all(
            "select odid, count(*) from cards where odid != 0 group by odid"))
        for did, name in dyn:
            col.decks.remove([did])
            print(f"  removed {name!r}")

        left_loan = col.db.scalar("select count(*) from cards where odid != 0")
        left_dyn = sum(1 for d in col.decks.all_names_and_ids()
                       if col.decks.is_filtered(d.id))
        print(f"\nverify: cards still on loan: {left_loan} (want 0)")
        print(f"verify: filtered decks left: {left_dyn} (want 0)")
        for did, n in homes.items():
            now = col.db.scalar("select count(*) from cards where did=?", did)
            print(f"verify: {col.decks.name(did)} received its {n} back — now holds {now}")
        print(f"verify: total cards {col.card_count()}")
    finally:
        col.close()


if __name__ == "__main__":
    main()
