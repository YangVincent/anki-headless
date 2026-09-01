#!/usr/bin/env python3
"""Label the `liked` band by type, and send the connectives back to the curriculum.

WHY THIS EXISTS. 88 words were tagged `liked` on 2026-09-01 by a parallel session, from
word lists a model wrote for the semantic fields "emotions" and "connectives" -- not from
Vincent's reading, lookups or gaps. `liked` is a manual override that beats HSK level and
list order, so those 88 took the first twelve days of the queue in one batch.

Vincent keeps the emotions at the front and sends the connectives back:

  * every one of the 88 gets `set::emotions` or `set::connectives`, so the two projects
    stop being one undifferentiated blob
  * the connectives LOSE `liked`. They then fall into the curriculum band and arrive by
    HSK level, with the six that carry no level landing in the non-HSK tail -- which is
    "HSK first, then non-HSK", exactly as asked
  * the emotions KEEP `liked` and become the whole of band 0

Reversible: `like.py --unlike` on the emotions, or re-add `liked` to the connectives.
The `set::` tags stay either way and are what makes the two sets addressable at all.

Usage: bash freq_data/anki_op.sh split-liked freq_data/split_liked_band.py --apply
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path("/home/vincent/anki-headless")
sys.path.insert(0, str(ROOT))

import anki.collection  # noqa: E402,F401
from anki.collection import Collection  # noqa: E402

#: Classified by gloss: every one of these has a logical or discourse function.
CONNECTIVES = ("依据 前提 因而 机制 立场 除非 因素 层面 至于 途径 之所以 也就是说 以致 "
               "取决于 固然 基于 引发 总而言之 换言之 相比之下 综上所述 虽说 鉴于 使得 "
               "论点 反之 换句话说 再者 诚然 话虽如此").split()


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "collection.anki2"))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = set(CONNECTIVES)
    col = Collection(args.db)
    try:
        liked = col.find_notes("tag:liked")
        got_conn, got_emo, unliked = [], [], 0
        for nid in liked:
            note = col.get_note(nid)
            word = strip_html(note.fields[0])
            is_conn = word in conn
            tag = "set::connectives" if is_conn else "set::emotions"
            (got_conn if is_conn else got_emo).append(word)
            if args.apply:
                if tag not in note.tags:
                    note.add_tag(tag)
                if is_conn:
                    note.remove_tag("liked")
                col.update_note(note)
            if is_conn:
                unliked += 1

        absent = sorted(conn - set(got_conn))
        print(f"liked notes seen: {len(liked)}")
        print(f"  set::connectives: {len(got_conn)}  (lose `liked`)")
        print(f"  set::emotions   : {len(got_emo)}  (keep `liked`)")
        if absent:
            print(f"  connectives NOT found under tag:liked — {' '.join(absent)}")
        if not args.apply:
            print("\n(dry run; nothing written)")
            return

        print(f"\nverify: tag:liked notes now {len(col.find_notes('tag:liked'))} "
              f"(want {len(got_emo)})")
        print(f"verify: set::emotions {len(col.find_notes('tag:set::emotions'))}")
        print(f"verify: set::connectives {len(col.find_notes('tag:set::connectives'))}")
        both = len(col.find_notes("tag:set::connectives tag:liked"))
        print(f"verify: still both connective AND liked: {both} (want 0)")
    finally:
        col.close()


if __name__ == "__main__":
    main()
