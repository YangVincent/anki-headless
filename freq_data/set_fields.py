#!/usr/bin/env python3
"""Set named fields on the notes an Anki search returns.

`anki-cli edit --fields` assigns by POSITION and needs every field of the notetype in
order, which is unusable on ChineseVocabulary's fifteen. `anki_set.py replace` rewrites a
field with a regex, which cannot set a value outright. This fills that gap: name the
field, give the value.

Dry-run by default. It prints the old and the new value of every field it touches, and
re-reads each note afterwards to confirm the write.

Usage:
  freq_data/set_fields.py '<anki search>' --set Pinyin='dàyì, dàyi' --set Meaning='…'
                                          [--tag next::<name>]
  bash freq_data/anki_op.sh set-fields freq_data/set_fields.py '<search>' --set … --apply
"""
import sys, argparse, re

sys.path.insert(0, "/home/vincent/anki-headless")
from anki.collection import Collection

COL = "/home/vincent/anki-headless/collection.anki2"
MAX_NOTES = 50   # a field set is a hand edit; refuse to run it over a whole deck by mistake


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE",
                    help="repeatable; the value is taken literally, never a regex")
    ap.add_argument("--tag", action="append", default=[],
                    help="repeatable; a tag to add to each matched note")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--db", default=COL)
    args = ap.parse_args()

    pairs = []
    for item in args.set:
        if "=" not in item:
            print(f"--set needs FIELD=VALUE, got {item!r}"); return 2
        f, v = item.split("=", 1)
        pairs.append((f.strip(), v))
    if not pairs:
        print("nothing to set"); return 2

    col = Collection(args.db)
    try:
        nids = col.find_notes(args.query)
        print(f"query {args.query!r} -> {len(nids)} note(s)")
        if len(nids) > MAX_NOTES:
            print(f"refusing: {len(nids)} notes is over the {MAX_NOTES} cap for a hand edit")
            return 1
        touched = []
        for nid in nids:
            note = col.get_note(nid)
            names = [f["name"] for f in note.note_type()["flds"]]
            print(f"\nnote {nid}  {note.fields[0]}")
            for f, v in pairs:
                if f not in names:
                    print(f"   !! no field {f!r} on {note.note_type()['name']}; skipped")
                    continue
                old = re.sub(r"<[^>]+>", "", note[f]).strip()
                print(f"   [{f}]\n      was: {old[:160]}")
                print(f"      now: {v[:160]}")
                if args.apply:
                    note[f] = v
            for t in args.tag:
                if t in note.tags:
                    print(f"   tag {t}: already there")
                else:
                    print(f"   tag {t}: add")
                    if args.apply:
                        note.tags.append(t)
            if args.apply:
                col.update_note(note)
                touched.append(nid)

        if not args.apply:
            print("\nDRY RUN — nothing written")
            return 0
        bad = []
        for nid in touched:
            note = col.get_note(nid)
            for f, v in pairs:
                if f in [x["name"] for x in note.note_type()["flds"]] and note[f] != v:
                    bad.append((nid, f))
            for t in args.tag:
                if t not in note.tags:
                    bad.append((nid, f"tag {t}"))
        print(f"\nwrote {len(touched)} note(s)")
        print(f"VERIFY: {'every field holds its new value' if not bad else f'PROBLEMS {bad}'}")
        return 0 if not bad else 1
    finally:
        col.close()


if __name__ == "__main__":
    sys.exit(main())
