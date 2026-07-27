#!/usr/bin/env python3
"""Score page_read.py against the pages already confirmed by hand.

reading_marks.json holds what Vincent actually confirmed for pages 002-006, so those
are the ground truth. Recall matters far more than precision here: a missed word is a
word he never studies, whereas a spurious one he deletes in the form. A word is counted
correct if it matches exactly, or if one string contains the other (the underline extent
is genuinely ambiguous between e.g. 花臂 and 花臂男).

  page_read_bench.py --page 006
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/vincent/anki-headless/freq_data")
from page_read import read_page  # noqa: E402

ROOT = Path("/home/vincent/anki-headless")
MARKS = json.loads((ROOT / "reading_marks.json").read_text())


def match(a, b):
    return a == b or (len(a) >= 2 and a in b) or (len(b) >= 2 and b in a)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", required=True)
    ap.add_argument("--photo")
    a = ap.parse_args()

    truth = next((s["marked"] for s in MARKS["sources"] if s["page"] == a.page), None)
    if truth is None:
        sys.exit(f"no confirmed marks for page {a.page}")
    photo = Path(a.photo) if a.photo else ROOT / f"generated/pageview/page-{a.page}.png"

    got, usage = read_page(photo)

    hit = [t for t in truth if any(match(t, g) for g in got)]
    miss = [t for t in truth if t not in hit]
    spurious = [g for g in got if not any(match(t, g) for t in truth)]

    print(f"page {a.page}: {len(truth)} confirmed marks, model returned {len(got)}")
    print(f"  recall    {len(hit)}/{len(truth)} = {len(hit)/len(truth):.0%}")
    print(f"  precision {len(got)-len(spurious)}/{len(got)} = "
          f"{(len(got)-len(spurious))/max(len(got),1):.0%}")
    print(f"  missed    {' '.join(miss) if miss else '—'}")
    print(f"  spurious  {' '.join(spurious) if spurious else '—'}")
    print(f"  tokens    in {usage.input_tokens} out {usage.output_tokens}")


if __name__ == "__main__":
    main()
