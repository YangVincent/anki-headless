#!/usr/bin/env python3
"""What would a deck for one book actually contain? Measure before building.

    book_deck_eval.py <book.jsonl> ["<name>"] [--chapters 1,2]

The premise "make cards for the words I don't know" did not survive measurement the last
time this repo tried it. For 《十日终焉》, of 2,212 words worth studying only 31 had no card
at all: 765 were already studied, and the rest sat unseen in HSK or another live deck.
Building the naive deck would have created a thousand duplicates.

So this splits the book's unstudied vocabulary by what the collection ALREADY holds:

    studied elsewhere      a card exists and is not new — nothing to do
    unseen in a live deck  a card is queued in HSK / non-HSK / Mined — reposition it
    parked in Archive      a card exists but is suspended — promote it
    no card anywhere       the only rows that need a new note

Character names are dropped by name_filter, and words outside CC-CEDICT are excluded:
neither belongs on a card.
"""
import json
import sys
from collections import Counter
from pathlib import Path

# anki_cache lives at the repo root, and the import below runs before anki_coverage
# extends sys.path for it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anki_cache as ac
import anki_coverage as ak
import coldwindow_words as cw
import name_filter as nf


def bucket(word, cards):
    if not cards:
        return "no card anywhere"
    if any(role != "archive" and status != "new" for _, role, status in cards):
        return "studied elsewhere"
    if any(role != "archive" for _, role, _ in cards):
        return "unseen in a live deck"
    return "parked in Archive"


def main():
    from wordfreq import zipf_frequency
    path = Path(sys.argv[1])
    label = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else path.stem
    only = None
    if "--chapters" in sys.argv:
        only = {int(x) for x in sys.argv[sys.argv.index("--chapters") + 1].split(",")}

    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if only:
        rows = [r for r in rows if r.get("chapter") in only]
    text, _ = ak.to_simplified("\n".join(r.get("text", "") for r in rows))

    cedict, surnames = nf.load_cedict()
    k = ak.load()
    counts, tags = cw.profile(text)
    total = sum(counts.values())

    con = ac.connect_ro()
    cards = {}
    for r in con.execute("select simplified, deck, role, status from words"):
        w = r["simplified"]
        if ac._is_plain_word(w):
            cards.setdefault(w, []).append((r["deck"], r["role"], r["status"]))

    todo, names = [], 0
    for w, n in counts.items():
        if w in k.known:
            continue
        if nf.score(w, n, total, zipf_frequency(w, "zh"), tags.get(w, set()),
                    cedict, surnames)[0] >= nf.THRESHOLD:
            names += 1
            continue
        if w not in cedict:
            continue
        todo.append((w, n, bucket(w, cards.get(w))))

    print(f"《{label}》 {len(rows)} chapters, {len(text):,} characters")
    print(f"  content words: {total:,} tokens, {len(counts):,} distinct")
    print(f"  character names filtered: {names}")
    print(f"  dictionary words you have NOT studied: {len(todo):,}\n")
    tally = Counter(b for _, _, b in todo)
    for name in ("no card anywhere", "parked in Archive", "unseen in a live deck",
                 "studied elsewhere"):
        print(f"    {name:<24}{tally.get(name, 0):>6}")
    # Cumulative AND banded. Reporting `>= lo` under a label like "5-9 times" reads as
    # a band and is not one; that mislabelling made a 907 look like a 1,438.
    print(f"\n  {'appears':<12}{'words':>7}{'new notes':>11}{'cumulative':>12}{'cum. new':>10}")
    bands = [(10, 10**9, "10+"), (5, 9, "5-9"), (3, 4, "3-4"), (2, 2, "twice"), (1, 1, "once")]
    for lo, hi, name in bands:
        band = [t for t in todo if lo <= t[1] <= hi]
        cum = [t for t in todo if t[1] >= lo]
        print(f"  {name:<12}{len(band):>7}"
              f"{sum(1 for t in band if t[2] == 'no card anywhere'):>11}"
              f"{len(cum):>12}"
              f"{sum(1 for t in cum if t[2] == 'no card anywhere'):>10}")
    top = sorted((t for t in todo if t[1] >= 3), key=lambda t: -t[1])[:14]
    print("\n  most frequent: " + "  ".join(f"{w}x{n}" for w, n, _ in top))


if __name__ == "__main__":
    main()
