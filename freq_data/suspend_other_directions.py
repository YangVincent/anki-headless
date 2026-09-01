#!/usr/bin/env python3
"""Suspend every production and cloze card, leaving only Chinese->English live.

Vincent reviews one direction: 19,675 of 19,924 reviews in the last 90 days were
Chinese->English, against 154 English-Speaking and 95 Cloze-Recall. The other two
directions are off. bot.GATE_DISABLED stops any NEW release; this suspends the 4,075
cards already released, which would otherwise still surface if either deck were opened.

Nothing is deleted and no history is touched: suspending sets queue=-1 and leaves
type, interval, due and every revlog row alone. Unsuspending is one search away, and
removing a template from bot.GATE_DISABLED turns the release rule back on.

Decks are resolved by ROLE, never by name.

Usage: bash freq_data/anki_op.sh suspend-other freq_data/suspend_other_directions.py --apply
"""
import argparse
import sys
from pathlib import Path

ROOT = Path("/home/vincent/anki-headless")
sys.path.insert(0, str(ROOT))

import anki.collection  # noqa: E402,F401
from anki.collection import Collection  # noqa: E402

import decks  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "collection.anki2"))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    col = Collection(args.db)
    try:
        targets = []
        for role in (decks.PRODUCTION, decks.CLOZE):
            did = decks.deck_id_for(col, role)
            live = col.db.list("select id from cards where did=? and queue != -1", did)
            reviewed = col.db.scalar(
                "select count(*) from cards where did=? and queue != -1 and reps > 0", did)
            targets.append((role, col.decks.name(did), did, live, reviewed))
            print(f"{role:<12}{col.decks.name(did):<10}live {len(live):>6}"
                  f"   of which already studied: {reviewed}")

        total = sum(len(t[3]) for t in targets)
        print(f"\nwould suspend {total} cards")
        if not args.apply:
            print("(dry run; pass --apply to suspend)")
            return

        for role, name, did, live, _ in targets:
            if live:
                col.sched.suspend_cards(live)

        print()
        for role, name, did, live, _ in targets:
            still = col.db.scalar("select count(*) from cards where did=? and queue != -1", did)
            print(f"verify: {name} live cards now {still} (want 0)")
        # The one direction that must be untouched.
        rec = decks.deck_ids_for(col, decks.RECOGNITION)
        marks = ",".join("?" * len(rec))
        live_rec = col.db.scalar(
            f"select count(*) from cards where did in ({marks}) and queue != -1", *rec)
        print(f"verify: recognition cards still live: {live_rec}")
        print(f"verify: total cards {col.card_count()} (unchanged)")
        print(f"verify: revlog rows {col.db.scalar('select count(*) from revlog')} (unchanged)")
    finally:
        col.close()


if __name__ == "__main__":
    main()
