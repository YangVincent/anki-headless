"""Convert numeric-tone pinyin (chuai1, dao3ti3) to tone marks (chuāi, dǎotǐ).

TWO TRAPS, both hit while writing this.

  * THE SUBSTITUTION MUST SKIP MARKUP. Many Pinyin fields are styled HTML like
    `<span class="tone4">bái</span>`, and the syllable pattern matches `tone4` just as
    happily as `wan4`. A naive re.sub over the raw field rewrites the CSS class to
    `tonè` and silently breaks the card. This splits on tags and transforms text nodes
    only, then asserts the tag sequence is byte-identical before and after.

  * SYLLABLES RUN TOGETHER. `ban4 dao3ti3` is three syllables, not two. A pattern that
    demands a non-alphanumeric on the right converts `ban4` and leaves `dao3ti3` intact,
    which looks fixed in a spot check and is not. The pattern deliberately has no right
    boundary so it consumes a run left to right.

Scope defaults to the studied set: 101 live fields, against 5,335 more in suspended
archive notes that nobody reads. --all includes those.

Run through freq_data/anki_op.sh. Dry-run by default; pass --apply to write.
"""
import argparse
import html
import re
import sys

from anki.collection import Collection
from pypinyin.contrib.tone_convert import to_tone

COL = "/home/vincent/anki-headless/collection.anki2"
SYL = re.compile(r"([a-zA-ZüÜv]{1,6}[1-5])")
TAGS = re.compile(r"(<!--.*?-->|<[^>]+>)", re.S)
# Detection ignores markup, so a `class="tone4"` never counts as a hit.
DETECT = re.compile(r"(?<![A-Za-z0-9])([a-zA-ZüÜv]{1,6}[1-5])")


def convert(raw: str) -> str:
    parts = TAGS.split(raw)
    for i in range(0, len(parts), 2):          # even = text, odd = tag/comment
        parts[i] = SYL.sub(lambda m: to_tone(m.group(1)), parts[i])
    return "".join(parts)


def has_numeric(raw: str) -> bool:
    return bool(DETECT.search(html.unescape(TAGS.sub("", raw))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="include suspended notes (the archive; ~5,335 more fields)")
    ap.add_argument("--show", type=int, default=12)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    col = Collection(COL)
    try:
        live = {c.nid for c in
                (col.get_card(i) for i in col.find_cards("deck:* -is:suspended"))}
        targets = []
        for m in col.models.all():
            idx = [i for i, f in enumerate(m["flds"]) if "inyin" in f["name"]]
            if not idx:
                continue
            for nid in col.models.nids(m["id"]):
                if not args.all and nid not in live:
                    continue
                note = col.get_note(nid)
                for i in idx:
                    raw = note.fields[i]
                    if has_numeric(raw):
                        targets.append((nid, i, m["flds"][i]["name"], raw, convert(raw)))

        print(f"fields to fix: {len(targets)}"
              f"{' (ALL, archive included)' if args.all else ' (studied set only)'}")
        for nid, i, fname, old, new in targets[:args.show]:
            print(f"  {nid} {fname}")
            print(f"      was: {old[:70]}")
            print(f"      now: {new[:70]}")
        if len(targets) > args.show:
            print(f"      ... and {len(targets)-args.show} more")

        # Refuse to write if any conversion touched markup or left a tone digit behind.
        bad = [t for t in targets
               if TAGS.findall(t[3]) != TAGS.findall(t[4]) or has_numeric(t[4])]
        if bad:
            sys.exit(f"\nABORT: {len(bad)} conversion(s) altered markup or left a digit; "
                     f"first: {bad[0][0]}")
        print("\nchecked: no conversion altered markup, none left a tone digit")

        if not args.apply:
            print("DRY-RUN (pass --apply to write)")
            return

        by_note = {}
        for nid, i, _f, _o, new in targets:
            by_note.setdefault(nid, []).append((i, new))
        for nid, edits in by_note.items():
            note = col.get_note(nid)
            for i, new in edits:
                note.fields[i] = new
            col.update_note(note)
        print(f"wrote {len(by_note)} note(s), {len(targets)} field(s)")

        left = 0
        for nid, i, _f, _o, _n in targets:
            if has_numeric(col.get_note(nid).fields[i]):
                left += 1
        print(f"verify: fields still holding numeric pinyin = {left}")
        assert left == 0
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
