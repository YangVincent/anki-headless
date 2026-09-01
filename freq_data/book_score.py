#!/usr/bin/env python3
"""Score one book file with both difficulty metrics and the name filter.

    book_score.py <book.jsonl> ["<name>"]

The file holds one JSON object per line with a `text` field, which is what
coldwindow_book.py writes and what difficulty_report.py reads.

Reports the frequency metric (tap-calibrated) and the collection metric side by side,
so a book fetched in full can be compared against the three-chapter samples.
"""
import json
import sys
from pathlib import Path

import anki_coverage as ak
import coldwindow_words as cw
import difficulty_report as dr
import name_filter as nf


def score_text(text, knowledge, tapped, frontier, cedict, surnames):
    from wordfreq import zipf_frequency
    text, converted = ak.to_simplified(text)
    counts, tags = cw.profile(text)
    total = sum(counts.values())
    names = {w for w, n in counts.items()
             if nf.score(w, n, total, zipf_frequency(w, "zh"),
                         tags.get(w, set()), cedict, surnames)[0] >= nf.THRESHOLD}
    freq = dr.score(text, max(len(text) // 1000, 1), tapped, frontier,
                    proper=dr.PROPER | names)
    coll = ak.cover(text, knowledge, drop=names)
    return text, converted, names, freq, coll


def main():
    path = Path(sys.argv[1])
    label = sys.argv[2] if len(sys.argv) > 2 else path.stem
    lines = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    text = "\n".join(r.get("text", "") for r in lines)

    knowledge = ak.load()
    frontier, tapped, _ = dr.tap_frontier()
    cedict, surnames = nf.load_cedict()
    text, converted, names, freq, coll = score_text(
        text, knowledge, tapped, frontier, cedict, surnames)

    print(f"《{label}》 {len(lines)} chapters, {len(text):,} chars"
          + ("  (converted from traditional)" if converted else ""))
    print(f"  frequency metric : effective lookup {freq['effective']:.1f}%  "
          f"— {dr.band(freq['effective'])}")
    print(f"  your collection  : known {coll['coverage']:.1f}%  guessable "
          f"{coll['transparent_pct']:.1f}%  new {coll['opaque_pct']:.1f}%  "
          f"new characters {coll['unseen_char_pct']:.1f}%")
    print(f"  names filtered   : {len(names)}")
    print("  top new words    : "
          + "  ".join(f"{w}x{n}" for w, n in coll["top_unknown"][:10]))


if __name__ == "__main__":
    main()
