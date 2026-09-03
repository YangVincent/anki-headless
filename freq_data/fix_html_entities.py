#!/usr/bin/env python3
"""Repair HTML entities in note fields — the ones that are wrong, and only those.

A field here RENDERS AS HTML on the card, so an entity is not automatically a defect.
`&amp;` is the correct way to write a literal `&`, and `&quot;` a literal quote. Replacing
those would be a regression, not a cleanup. Measured over the whole collection, the 1,361
entity occurrences split three ways:

  A  315 in 122 notes   `&lt;br /&gt;` and friends — a TAG that was escaped twice, so the
                        card shows the literal text "<br />" where a line break belongs.
                        THIS IS THE DEFECT. Both halves of the sentence run together on
                        one line, in Simplified, Pinyin and Meaning alike.
  B  248 in 130 notes   `&amp;`, `&quot;`, and bare `&lt;`/`&gt;` that form no tag.
                        CORRECT HTML. Left alone.
  C  483 in 405 notes   `&nbsp;`. Renders as a space either way, so nothing is visibly
                        broken; it is paste residue. Folded to a real space so the text
                        can be searched, sorted and diffed like any other.

The A/B split is the whole point, and a blanket html.unescape() cannot make it: it would
turn `Taiwan &amp; Hong Kong` into `Taiwan & Hong Kong` (fine) and `1. &quot;silk&quot;
radical` into `1. "silk" radical` (fine) but ALSO leave a field whose literal `<` was
deliberately escaped indistinguishable from one that was double-escaped by an importer.
Only the tag shape separates them, so only the tag shape is matched.

Not touched, and not this script's business: several SentenceSimplified fields hold OCR
garbage ('且1眨酌 ILlJ，. ~1. lI!l=+J.b.~昼由'). They show up here only because the same
noise contains `&quot;`.

Usage:
    freq_data/fix_html_entities.py                  # dry run
    bash freq_data/anki_op.sh fix-entities \\
         freq_data/fix_html_entities.py --apply
"""
import argparse
import collections
import re

from anki.collection import Collection

ROOT = "/home/vincent/anki-headless"

#: A tag name that was escaped instead of written. Anchored on a real tag name so a
#: literal "a &lt; b" comparison is never caught: only `&lt;` immediately introducing one
#: of these words counts as a tag somebody meant to render.
TAG_NAMES = ("br", "div", "b", "i", "u", "em", "strong", "span", "p", "hr",
             "ul", "li", "ol", "sub", "sup", "font")
TAGISH = re.compile(r"&lt;\s*(/?\s*(?:" + "|".join(TAG_NAMES) + r")\b[^&]*?)/?\s*&gt;",
                    re.IGNORECASE)


def unescape_tags(text):
    """`&lt;br /&gt;` -> `<br>`. Leaves every other entity untouched."""
    return TAGISH.sub(lambda m: "<" + m.group(1).strip().rstrip("/").strip() + ">", text)


def fold_nbsp(text):
    """`&nbsp;` -> a real space, and trim the field. Not a whitespace collapse: a run of
    spaces inside the text may be deliberate, and this pass has no way to tell."""
    return text.replace("&nbsp;", " ").strip()


def repair(text):
    return fold_nbsp(unescape_tags(text or ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    col = Collection(args.db)
    try:
        changed, per_field = [], collections.Counter()
        tags_fixed = nbsp_folded = 0
        for nid in col.find_notes(""):
            note = col.get_note(nid)
            names = [f["name"] for f in note.note_type()["flds"]]
            touched = False
            for i, (fname, val) in enumerate(zip(names, note.fields)):
                new = repair(val)
                if new == (val or ""):
                    continue
                tags_fixed += len(TAGISH.findall(val or ""))
                nbsp_folded += unescape_tags(val or "").count("&nbsp;")
                per_field[fname] += 1
                if len(changed) < 12:
                    changed.append((nid, fname, (val or "")[:70], new[:70]))
                note.fields[i] = new
                touched = True
            if touched and args.apply:
                col.update_note(note)

        print(f"escaped tags restored : {tags_fixed}")
        print(f"&nbsp; folded         : {nbsp_folded}")
        print(f"fields changed        : {sum(per_field.values())}")
        for f, n in per_field.most_common():
            print(f"    {n:5d}  {f}")
        print("\nsample:")
        for nid, f, before, after in changed:
            print(f"  {nid} {f}\n      - {before!r}\n      + {after!r}")

        if not args.apply:
            print("\nDRY-RUN — nothing written.")
        else:
            # Verify inside the stopped-bot window, as anki_op.sh requires.
            left_tags = left_nbsp = kept_ok = 0
            OK = re.compile(r"&(amp|quot|apos|#\d+);")
            for nid in col.find_notes(""):
                n = col.get_note(nid)
                for val in n.fields:
                    v = val or ""
                    left_tags += len(TAGISH.findall(v))
                    left_nbsp += v.count("&nbsp;")
                    kept_ok += len(OK.findall(v))
            print(f"\nVERIFY: escaped tags remaining: {left_tags} (want 0)")
            print(f"VERIFY: &nbsp; remaining:       {left_nbsp} (want 0)")
            print(f"VERIFY: correct entities kept:  {kept_ok} (must NOT be 0)")
            if left_tags or left_nbsp:
                raise SystemExit("verification failed")
            if not kept_ok:
                raise SystemExit("verification failed — the legitimate entities are gone too")
    finally:
        col.close()


if __name__ == "__main__":
    main()
