#!/usr/bin/env python3
"""Merge each mined word's suspended twin into the live note, then delete the twin.

145 of the 515 mined words have a second note. The mining import re-created words the
collection already had. In every case exactly one note is live (Mined, HSK7-9 or
non-HSK) and the other sits suspended in Archive -- so nothing double-shows -- but the
ARCHIVED copy is often the richer one: 26 carry an example sentence the live note lacks,
plus a handful of PartOfSpeech, Frequency and Notes values.

WHAT IS CARRIED: any field the twin fills and the live note leaves empty, EXCEPT audio.
Vincent does not want audio, and 68 twins differ only by an Audio reference.

WHAT IS NOT CARRIED: HSK tags. Exactly 3 twins hold an HSK tag the live note lacks --
气概, 惹祸 and 疼爱 -- and all three words are ABSENT from hsk30_official.json. They are
residue from the corrupt PDF-parse tagging, so carrying them would spread bad data.

  bash freq_data/anki_op.sh mergedupes freq_data/merge_mined_dupes.py --apply
"""
import argparse
import sys
from collections import defaultdict

from anki.collection import Collection

COL = "/home/vincent/anki-headless/collection.anki2"
SKIP = ("Audio", "SentenceAudio")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=COL)
    ap.add_argument("--show", type=int, default=10)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    col = Collection(args.db)
    try:
        cv = col.models.by_name("ChineseVocabulary")
        names = [f["name"] for f in cv["flds"]]
        si = names.index("Simplified")
        carry = [i for i, n in enumerate(names) if n not in SKIP and n != "Simplified"]

        by = defaultdict(list)
        for nid in col.models.nids(cv["id"]):
            note = col.get_note(nid)
            w = note.fields[si].strip()
            if not w:
                continue
            row = col.db.first("SELECT queue FROM cards WHERE nid=? AND ord=0", nid)
            by[w].append((nid, "mined" in [t.lower() for t in note.tags],
                          row[0] if row else None))

        groups = [(w, v) for w, v in by.items()
                  if len(v) > 1 and any(m for _, m, _ in v)]
        filled = 0
        plan = []
        for w, v in groups:
            live = [x for x in v if x[2] is not None and x[2] >= 0]
            dead = [x for x in v if x[2] == -1]
            if len(live) == 1 and len(dead) == 1:
                keep, drop = live[0], dead[0]
            elif not live and len(v) == 2:
                # BOTH suspended. Common now that Vincent suspends during review, and it
                # was 77 of 145 groups. The mined note is still the keeper -- it is the one
                # in his Mined deck and the one his tooling tracks; the Archive copy is the
                # import's leftover either way.
                mined = [x for x in v if x[1]]
                other = [x for x in v if not x[1]]
                if len(mined) != 1 or len(other) != 1:
                    print(f"  SKIP {w}: cannot tell the copies apart, needs a human")
                    continue
                keep, drop = mined[0], other[0]
            else:
                print(f"  SKIP {w}: {len(live)} live / {len(dead)} suspended, needs a human")
                continue
            L, D = col.get_note(keep[0]), col.get_note(drop[0])
            gained = [(i, D.fields[i]) for i in carry
                      if D.fields[i].strip() and not L.fields[i].strip()]
            plan.append((w, L, D, gained))
            filled += len(gained)

        print(f"groups: {len(groups)}   mergeable: {len(plan)}   "
              f"fields to carry: {filled}")
        for w, L, D, g in plan[:args.show]:
            if g:
                print(f"  {w}: +{', '.join(names[i] for i, _ in g)}")
        print(f"  ... plus {sum(1 for p in plan if not p[3])} with nothing to carry")

        if not args.apply:
            print("\nDRY-RUN (pass --apply)")
            return

        for w, L, D, gained in plan:
            if gained:
                for i, val in gained:
                    L.fields[i] = val
                col.update_note(L)
        col.remove_notes([D.id for _, _, D, _ in plan])

        # verify: every merged word now has exactly one note, and the carried fields stuck
        bad = 0
        for w, L, D, gained in plan:
            n = col.db.scalar("SELECT count(*) FROM notes WHERE mid=? AND flds LIKE ?",
                              cv["id"], w + chr(31) + "%")
            if n != 1:
                print(f"  FAIL {w}: {n} notes remain"); bad += 1
            fresh = col.get_note(L.id)
            for i, val in gained:
                if fresh.fields[i] != val:
                    print(f"  FAIL {w}: {names[i]} did not stick"); bad += 1
        print(f"\ndeleted {len(plan)} twin(s), carried {filled} field(s), {bad} failure(s)")
        assert bad == 0
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
