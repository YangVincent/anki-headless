#!/usr/bin/env python3
"""Drop HSK::HSKn tags that contradict the official HSK 3.0 band for the note's word.

hsk_retag_official.py guarantees the CORRECT tag is present, but it does not remove a
stale extra one, so a handful of notes carry two levels at once:

    拿    HSK::HSK1 + HSK::HSK7-9     official: level 1 only
    蓝    HSK::HSK2 + HSK::HSK7-9     official: level 2 only
    凉快  HSK::HSK2 + HSK::HSK4       official: level 2 only

That matters because resort_main_queue.level_of() reads the tag, so a note claiming two
levels sorts by whichever it sees first. 96 HSK 3.0 words genuinely sit in two bands, and
those are left alone — only tags OUTSIDE a word's official band(s) are removed.

Scope: notes with at least one card outside the Archive deck. Every Archive card is
suspended (213,311 of them) and it exists as a frozen backup pool, so its 204 stale tags
are inert and rewriting them would only churn the backup.

Usage:
    freq_data/hsk_fix_duplicate_level_tags.py                 # dry run
    bash freq_data/anki_op.sh hsk-dupe-tags \\
         freq_data/hsk_fix_duplicate_level_tags.py --apply
"""
import argparse
import json
import re

from anki.collection import Collection

ROOT = "/home/vincent/anki-headless"
OFFICIAL = f"{ROOT}/freq_data/hsk30_official.json"
TAG = re.compile(r"^HSK::HSK([1-6]|7-9)$")
HANZI = re.compile(r"^[一-鿿〇]+$")


def strip_html(s):
    return re.sub(r"<[^>]+>|\[sound:[^\]]*\]", "", s or "").replace("&nbsp;", " ").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    bands = {}
    for e in json.load(open(OFFICIAL, encoding="utf-8")):
        bands.setdefault(e["word"], set()).update(e["levels"])

    col = Collection(args.db)
    try:
        archive = {d.id for d in col.decks.all_names_and_ids() if d.name == "Archive"}

        fixed, skipped_archive = [], 0
        for nid in col.find_notes("tag:HSK::HSK*"):
            note = col.get_note(nid)
            word = strip_html(note.fields[0])
            if not HANZI.match(word) or word not in bands:
                continue

            tagged = {m.group(1) for m in (TAG.match(t) for t in note.tags) if m}
            stale = tagged - bands[word]
            if not stale:
                continue

            dids = {c.did for c in note.cards()}
            if dids <= archive:
                skipped_archive += 1
                continue

            keep = [t for t in note.tags if not (TAG.match(t) and TAG.match(t).group(1) in stale)]
            fixed.append((word, sorted(bands[word]), sorted(stale)))
            if args.apply:
                note.tags = keep
                col.update_note(note)

        for word, official, removed in fixed:
            print(f"  {word:<6} official band(s) {'/'.join(official):<8} "
                  f"removed HSK::HSK{' HSK::HSK'.join(removed)}")
        print(f"\nnotes fixed: {len(fixed)}")
        print(f"Archive-only notes left alone (all suspended): {skipped_archive}")

        if not args.apply:
            print("\nDRY-RUN — nothing written.")
        else:
            # Verify inside the stopped-bot window, as anki_op.sh requires.
            remaining = 0
            for nid in col.find_notes("tag:HSK::HSK*"):
                note = col.get_note(nid)
                word = strip_html(note.fields[0])
                if not HANZI.match(word) or word not in bands:
                    continue
                tagged = {m.group(1) for m in (TAG.match(t) for t in note.tags) if m}
                if tagged - bands[word] and not {c.did for c in note.cards()} <= archive:
                    remaining += 1
            print(f"VERIFY: contradictory tags outside Archive after write: {remaining}")
            if remaining:
                raise SystemExit("verification failed — tags remain")
    finally:
        col.close()


if __name__ == "__main__":
    main()
