#!/usr/bin/env python3
"""Make HSK tags on LIVE notes agree with hsk30_official.json.

SCOPE IS DELIBERATELY THE STUDIED SET. Measured across every notetype, the tags disagree
with the official list 50,000+ times -- but 44,160 of those are the suspended
"Basic - new hsk 3.0 xiehanzi" archive import (never tagged at all) and 5,625 are
ChineseSentences notes, where an HSK tag is meaningless. On cards Vincent actually sees,
exactly 7 notes are wrong. Retagging the archive would rewrite 50k notes nobody reads.

THREE KINDS OF WRONG, and one is a trap:
  * tagged but absent from the official list  -> drop the HSK tags
  * a stale level beside the right one        -> drop the stale one
  * `保守 (not just guard)` looked untagged-but-official, and it is NOT a tag problem at
    all: the parenthetical sits INSIDE the Simplified field, so the lookup missed. The
    tag is correct; the FIELD is malformed. Fixing the tag would have been the wrong
    repair, and would have removed a correct HSK4 tag.

  bash freq_data/anki_op.sh hsktags freq_data/fix_hsk_tags.py --apply
"""
import argparse
import json
import re
import sys

from anki.collection import Collection

COL = "/home/vincent/anki-headless/collection.anki2"
OFFICIAL = "/home/vincent/anki-headless/freq_data/hsk30_official.json"
LV = re.compile(r"^HSK::HSK([0-9\-]+)$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=COL)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    off = {x["word"]: x["level"] for x in json.load(open(OFFICIAL, encoding="utf-8"))}
    col = Collection(args.db)
    try:
        live = {c.nid for c in (col.get_card(i)
                                for i in col.find_cards("deck:* -is:suspended"))}
        edits = []
        for m in col.models.all():
            names = [f["name"] for f in m["flds"]]
            if "Simplified" not in names:
                continue
            si = names.index("Simplified")
            for nid in col.models.nids(m["id"]):
                if nid not in live:
                    continue
                note = col.get_note(nid)
                raw = note.fields[si].strip()
                # the malformed-field case: strip a trailing latin parenthetical
                clean = re.sub(r"\s*\([^)]*[A-Za-z][^)]*\)\s*$", "", raw).strip()
                word = clean if clean in off else raw
                want = off.get(word)
                have = [t for t in note.tags if LV.match(t)]
                newtags = list(note.tags)
                why = []
                if raw != clean and clean in off:
                    why.append(f"field {raw!r} -> {clean!r}")
                if want is None:
                    if have:
                        newtags = [t for t in newtags
                                   if not LV.match(t) and t.upper() != "HSK"]
                        why.append(f"not official: drop {have}")
                else:
                    good = f"HSK::HSK{want}"
                    stale = [t for t in have if t != good]
                    if stale:
                        newtags = [t for t in newtags if t not in stale]
                        why.append(f"drop stale {stale}")
                    if good not in newtags:
                        newtags.append(good)
                        why.append(f"add {good}")
                if why:
                    edits.append((nid, si, raw, clean if raw != clean and clean in off
                                  else raw, note.tags[:], newtags, why))

        print(f"live notes needing a tag or field fix: {len(edits)}")
        for nid, si, raw, newraw, old, new, why in edits:
            print(f"  {raw[:26]:26s} {'; '.join(why)}")
            print(f"       tags {old} -> {new}")
        if not args.apply:
            print("\nDRY-RUN (pass --apply)")
            return

        for nid, si, raw, newraw, old, new, why in edits:
            note = col.get_note(nid)
            note.fields[si] = newraw
            note.tags = new
            col.update_note(note)

        bad = 0
        for nid, si, raw, newraw, old, new, why in edits:
            n = col.get_note(nid)
            w = n.fields[si].strip()
            want = off.get(w)
            have = [t for t in n.tags if LV.match(t)]
            ok = (have == [f"HSK::HSK{want}"]) if want else (have == [])
            if not ok:
                print(f"  FAIL {w}: tags {have}, official {want}"); bad += 1
        print(f"\nfixed {len(edits)} note(s), {bad} failure(s)")
        assert bad == 0
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
