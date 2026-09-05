#!/usr/bin/env python3
"""Rewrite a named card's Meaning (and optionally Notes) from a reviewed data file.

Not a one-off: gloss faults come in ones and twos and keep arriving, so the fix is a
data file plus this runner, rather than a new script each time. Each entry carries a
`why`, because a gloss change is a judgement and the reason has to survive the commit.

The faults this exists for are NOT mechanical. A stripped CC-CEDICT dump is still a dump:
the numbering is gone but the SENSE ORDER is the dictionary's, and the dictionary's first
sense is often not the word you meet. 使得 sat at queue position 1 reading "usable;
workable; feasible; doable; to make; to cause" -- four glosses for a colloquial sense the
card never teaches, ahead of the written causative that its own Notes field describes and
its own sentence uses. No regex finds that; it needs the gloss read against the card.

Usage: bash freq_data/anki_op.sh fix-glosses freq_data/fix_glosses.py --apply
       (add --data <path> for a different file)
"""
import argparse
import json
import re
import sys

from anki.collection import Collection

ROOT = "/home/vincent/anki-headless"
DEFAULT = f"{ROOT}/freq_data/gen_heian/glosses.json"
# The deck's own gloss rule: a short dictionary gloss, not a paragraph. Anything longer
# is flagged for review rather than written.
MAX_MEANING = 70


def strip_html(s):
    s = re.sub(r"\[sound:[^\]]*\]", "", s or "")
    return re.sub(r"<[^>]+>", "", s).replace("&nbsp;", " ").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--data", default=DEFAULT)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    data = json.load(open(args.data, encoding="utf-8"))
    col = Collection(args.db)
    try:
        # Resolve each word through an Anki search, so the scope is every notetype and
        # deck that actually matches, not a guess about where the note lives.
        targets = {}
        for w in data:
            nids = [n for n in col.find_notes(f'deck:Main "Simplified:{w}"')]
            if len(nids) != 1:
                sys.exit(f"{w}: expected 1 Main note, found {len(nids)}")
            targets[w] = nids[0]

        print("── changes ──")
        for w, spec in data.items():
            note = col.get_note(targets[w])
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            new = spec["meaning"]
            assert len(new) <= MAX_MEANING, (w, len(new))
            old = strip_html(note.fields[IX["Meaning"]])
            print(f"\n  {w}")
            print(f"    - {old}")
            print(f"    + {new}")
            print(f"    why: {spec['why']}")
            note.fields[IX["Meaning"]] = new
            if "notes" in spec:
                oldn = strip_html(note.fields[IX["Notes"]])
                print(f"    Notes: {'replacing' if oldn else 'was empty'}")
                note.fields[IX["Notes"]] = spec["notes"]
            if args.apply:
                col.update_note(note)

        if not args.apply:
            print("\nDRY-RUN — nothing written.")
            return

        print("\n── verify ──")
        bad = []
        for w, spec in data.items():
            note = col.get_note(targets[w])
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            if strip_html(note.fields[IX["Meaning"]]) != spec["meaning"]:
                bad.append((w, "Meaning did not take"))
            if "notes" in spec and strip_html(note.fields[IX["Notes"]]) != spec["notes"]:
                bad.append((w, "Notes did not take"))
            # a gloss must not reintroduce the dump artefacts already cleaned out
            m = strip_html(note.fields[IX["Meaning"]])
            if re.search(r"(?:^|; )\d{1,2}\.\s", m) or "CL:" in m or re.search(r"\bmw\b", m):
                bad.append((w, "reintroduced a dictionary artefact"))
        print(f"  problems: {len(bad)} (want 0)")
        for w, why in bad:
            print(f"    {w}: {why}")
        assert not bad
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
