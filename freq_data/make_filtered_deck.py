#!/usr/bin/env python3
"""Build a filtered deck from a tag, so a book's words study beside the backbone.

WHY NOT REPOSITION. Putting a book's words at the front of HSK is what promote_to_vocab()
does for a single wild-add, and it is wrong in bulk: 143 words jumped the queue and pushed
绝望 / 悲伤 / 心疼 back by 143 places, overriding resort_main_queue.py's canonical order.

A filtered deck BORROWS instead. Each card keeps `odid` and `odue` — its home deck and its
old queue position — so HSK studies its own order while the borrowed cards study beside it,
and deleting the filtered deck sends every card home with the progress it earned. Review
history is never at risk: the revlog is keyed on the card, and has no deck column at all.

Suspended cards are never gathered, so the gated Reverse and Cloze siblings stay put.

    make_filtered_deck.py --name 十年 --tag book::十年 [--limit N] [--apply]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path("/home/vincent/anki-headless")
sys.path.insert(0, str(ROOT))

import anki.collection  # noqa: E402,F401  — import first; the submodules import it back
from anki.collection import Collection  # noqa: E402
from anki.decks import FilteredDeckConfig  # noqa: E402

ORDER = FilteredDeckConfig.SearchTerm.Order


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "collection.anki2"))
    ap.add_argument("--name", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--empty", action="store_true",
                    help="send every borrowed card home and stop (the deck stays, empty)")
    args = ap.parse_args()

    search = f"tag:{args.tag} -is:suspended"
    col = Collection(args.db)
    try:
        if args.empty:
            did = col.decks.id_for_name(args.name)
            if did is None:
                print(f"no deck named {args.name!r}; nothing to empty")
                return
            before = len(col.find_cards(f'deck:"{args.name}"'))
            if args.apply:
                col.sched.empty_filtered_deck(did)
            print(f"emptied {args.name!r}: {before} cards -> home"
                  + ("" if args.apply else "  (dry run)"))
            if args.apply:
                print(f"verify: cards still in it: {len(col.find_cards(f'deck:\"{args.name}\"'))}")
                print(f"verify: cards still on loan anywhere: "
                      f"{col.db.scalar('select count(*) from cards where odid!=0')}")
            return
        eligible = col.find_cards(search)
        homes = {}
        for cid in eligible:
            homes[col.get_card(cid).current_deck_id()] = \
                homes.get(col.get_card(cid).current_deck_id(), 0) + 1
        print(f"search: {search}")
        print(f"cards it would gather: {len(eligible)} (limit {args.limit})")
        for did, n in sorted(homes.items(), key=lambda kv: -kv[1]):
            print(f"  from {col.decks.name(did)}: {n}")
        if not args.apply:
            print("\n(dry run; pass --apply to build)")
            return

        deck = col.sched.get_or_create_filtered_deck(deck_id=0)
        deck.name = args.name
        cfg = deck.config
        del cfg.search_terms[:]
        cfg.search_terms.append(FilteredDeckConfig.SearchTerm(
            search=search, limit=args.limit, order=ORDER.DUE))
        # Explicit, never inherited: the collection stores withScheduling=false as the
        # dialog's remembered value, and with rescheduling off every answer is discarded
        # when the card goes home.
        cfg.reschedule = True
        out = col.sched.add_or_update_filtered_deck(deck)

        did = out.id
        gathered = col.find_cards(f'deck:"{args.name}"')
        print(f"\nverify: filtered deck {args.name!r} id={did}, gathered {len(gathered)} cards")
        print(f"verify: reschedule = {col.decks.get(did)['resched']}")
        stranded = col.db.scalar("select count(*) from cards where did=? and odid=0", did)
        print(f"verify: cards with no home recorded: {stranded} (want 0)")
        for name in decks.RECOGNITION_DECKS:
            print(f"verify: {name} still holds "
                  f"{len(col.find_cards(f'deck:{name} is:new'))} new cards")
    finally:
        col.close()


if __name__ == "__main__":
    main()
