#!/usr/bin/env python3
"""Put the rescued chengyu back to their natural position in Mined.

They were pushed to the front of the Mined queue during the non-HSK purge. That was not
asked for -- the rescue was about keeping them, not about prioritising them. Mined is
frequency-ordered, so they belong wherever their frequency puts them.

This re-sorts the WHOLE Mined new queue by zipf, descending, which is that deck's rule
(mined_deck.py). Cards tagged `liked` keep the front, mirroring resort_hsk_queue.py.

Dry-run unless --apply. Run through freq_data/anki_op.sh.
"""
import argparse
import re

from anki.collection import Collection
from wordfreq import zipf_frequency

COL = "/home/vincent/anki-headless/collection.anki2"
DECK = "Mined"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    col = Collection(COL)
    try:
        did = col.decks.id_for_name(DECK)
        rows = col.db.all(
            "SELECT c.id, n.sfld, n.tags FROM cards c JOIN notes n ON n.id=c.nid "
            "WHERE c.did=? AND c.type=0 AND c.ord=0", did)
        order = []
        for cid, sfld, tags in rows:
            w = re.sub(r"<[^>]+>", "", sfld or "").strip()
            liked = "liked" in [t.lower() for t in tags.split()]
            order.append((0 if liked else 1, -zipf_frequency(w, "zh"), cid, w,
                          "type::Chengyu" in tags))
        order.sort(key=lambda t: (t[0], t[1]))
        print(f"{DECK}: {len(order)} new cards to reposition")
        print("  first 12 after the sort:")
        for rank, negz, cid, w, ch in order[:12]:
            print(f"     {w:10s} zipf {-negz:4.2f} {'liked' if rank == 0 else ''}"
                  f"{'  chengyu' if ch else ''}")
        ch_pos = [i for i, o in enumerate(order, 1) if o[4]]
        if ch_pos:
            print(f"  chengyu land at positions {min(ch_pos)}-{max(ch_pos)} "
                  f"(median {sorted(ch_pos)[len(ch_pos)//2]})")
        if not args.apply:
            print("\nDRY-RUN (pass --apply)")
            return
        for pos, (_r, _z, cid, _w, _c) in enumerate(order, 1):
            c = col.get_card(cid)
            c.due = pos
            col.update_card(c)
        first = col.db.all(
            "SELECT n.sfld FROM cards c JOIN notes n ON n.id=c.nid "
            "WHERE c.did=? AND c.type=0 AND c.ord=0 ORDER BY c.due LIMIT 8", did)
        print(f"\nfront of {DECK} now: " + " ".join(r[0] for r in first))
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
