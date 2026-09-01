#!/usr/bin/env python3
"""Merge the HSK7-9 deck into HSK.

WHY. Measured over 21 days: 4,997 reviews in HSK, 26 in HSK7-9. The second deck is not
studied. Its 81 due cards (67 of them a week late) are not a backlog problem -- they are
a deck-that-never-opens problem, and a second daily habit has not formed in months.
Folding it into the deck that IS opened every day puts those 5,272 words in front of him,
ordered by HSK level, so 7-9 naturally sits behind levels 1-6.

WHAT MOVES: every card, review and new alike. Nothing is deleted, no note is touched, no
scheduling state is reset -- only `cards.did` changes, so intervals, due dates and lapse
counts all survive.

AFTER THIS, resort_hsk_queue.py must drop "HSK7-9" from DECKS or it will sort an empty
deck (harmless, but misleading). The `liked` and `demoted` tags keep working unchanged.

Run through freq_data/anki_op.sh. Dry-run by default; pass --apply to write.
"""
import argparse
import sys

from anki.collection import Collection

COL = "/home/vincent/anki-headless/collection.anki2"
SRC, DST = "HSK7-9", "HSK"


def census(col, did):
    q = lambda s: col.db.scalar(s, did)
    return dict(
        total=q("SELECT count(*) FROM cards WHERE did=?"),
        new=q("SELECT count(*) FROM cards WHERE did=? AND queue=0"),
        review=q("SELECT count(*) FROM cards WHERE did=? AND queue=2"),
        susp=q("SELECT count(*) FROM cards WHERE did=? AND queue=-1"),
        learn=q("SELECT count(*) FROM cards WHERE did=? AND queue IN (1,3)"),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    col = Collection(COL)
    try:
        src = col.decks.id_for_name(SRC)
        dst = col.decks.id_for_name(DST)
        if src is None:
            sys.exit(f"{SRC} does not exist -- already merged?")
        a, b = census(col, src), census(col, dst)
        print(f"{SRC:8s} {a}")
        print(f"{DST:8s} {b}")
        expect = {k: a[k] + b[k] for k in a}
        print(f"\nafter the merge {DST} should hold: {expect}")

        # scheduling must be untouched: snapshot a sample to compare afterwards
        sample = col.db.all(
            "SELECT id, type, queue, due, ivl, factor, reps, lapses FROM cards "
            "WHERE did=? ORDER BY id LIMIT 400", src)
        print(f"sampled {len(sample)} cards to verify scheduling survives")

        if not args.apply:
            print("\nDRY-RUN (pass --apply)")
            return

        cids = col.db.list("SELECT id FROM cards WHERE did=?", src)
        col.set_deck(cids, dst)

        after_src, after_dst = census(col, src), census(col, dst)
        print(f"\n{SRC} now: {after_src}")
        print(f"{DST} now: {after_dst}")
        assert after_src["total"] == 0, "cards left behind"
        assert after_dst == expect, (after_dst, expect)

        bad = 0
        for cid, typ, queue, due, ivl, factor, reps, lapses in sample:
            row = col.db.first(
                "SELECT did, type, queue, due, ivl, factor, reps, lapses "
                "FROM cards WHERE id=?", cid)
            if row[0] != dst or list(row[1:]) != [typ, queue, due, ivl, factor,
                                                  reps, lapses]:
                bad += 1
        print(f"verify: sampled cards whose scheduling changed = {bad}")
        assert bad == 0

        # the emptied deck's own new-limit override is now meaningless
        deck = col.decks.get(src)
        if deck.get("newLimit") is not None:
            deck.pop("newLimit", None)
            col.decks.save(deck)
            print(f"cleared the stale newLimit override on the empty {SRC}")
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
