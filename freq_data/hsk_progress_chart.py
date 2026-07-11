#!/usr/bin/env python3
"""ASCII HSK progress bar charts (HSK 3.0 by deck tag, or HSK 2.0 by word mapping).

Two modes:

  --standard 3.0   Progress through the HSK deck, bucketed by each card's HSK::HSKn
                   tag (the 9-band 2021 standard the deck is built on). This is the
                   "am I on HSK 4 yet" chart.

  --standard 2.0   Maps every word in the WHOLE collection onto the old 6-level HSK
                   2.0 vocabulary list (freq_data/hsk20_vocab.json) and reports the
                   same learned / to-do / suspended breakdown per old level. Answers
                   "where would I place on the pre-2021 HSK scale".

Status buckets (per card, aggregated per word by best status in 2.0 mode):
  learned    reps>0 or currently in learning/review/relearning (type != 0)
  to-do      new & never seen  (reps==0 and type==0 and queue != -1)
  suspended  queue == -1

Progress %% = learned / (learned + to-do)  -- suspended is EXCLUDED from the
denominator, matching the original chart. NOTE for a heritage speaker: at the low
levels the suspended band is mostly basics known and parked on purpose (see
hsk-basic-chars-suspended-intentionally), so real command there is ~100%%.

The collection is opened read-only via a scratch copy so it is safe to run while
anki-bot holds the live collection. Nothing is written back.

Usage:
  freq_data/hsk_progress_chart.py --standard 3.0
  freq_data/hsk_progress_chart.py --standard 2.0
"""
import argparse, os, re, shutil, sqlite3, sys, tempfile, json
from collections import defaultdict

ROOT = "/home/vincent/anki-headless"
COL = f"{ROOT}/collection.anki2"
HSK20 = f"{ROOT}/freq_data/hsk20_vocab.json"
STATUS_NAME = {2: "learned", 1: "todo", 0: "suspended"}


def clean(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def open_copy():
    """Copy the live collection to a temp file and open it read-only-ish."""
    tmp = tempfile.mktemp(suffix=".anki2")
    shutil.copy(COL, tmp)
    return sqlite3.connect(tmp), tmp


def bar(pct, width=20):
    n = int(pct / (100 / width))
    return "█" * n + "·" * (width - n)


def render(rows, level_label):
    """rows: list of (label, learned, todo, susp)."""
    print(f"{level_label:8}{'learned':>9}{'to-do':>7}{'susp':>6}{'total':>7}   progress (learned / active)")
    tl = td = ts = 0
    for label, le, to, su in rows:
        tl += le; td += to; ts += su
        total = le + to + su
        active = le + to
        pct = 100 * le / active if active else 0
        print(f"{label:8}{le:9}{to:7}{su:6}{total:7}   {bar(pct)} {pct:3.0f}%")
    total = tl + td + ts
    active = tl + td
    pct = 100 * tl / active if active else 0
    print(f"{'TOTAL':8}{tl:9}{td:7}{ts:6}{total:7}   {bar(pct)} {pct:3.0f}%")


def status_of(queue, type_, reps):
    if queue == -1:
        return 0                     # suspended
    if reps > 0 or type_ != 0:
        return 2                     # learned / seen
    return 1                         # new / to-do


def chart_30(db):
    """Progress through the HSK deck, bucketed by HSK::HSKn tag."""
    c = db.cursor()
    c.execute("SELECT id,name FROM decks")
    dids = [d for d, n in c.fetchall() if n == "HSK" or n.startswith("HSK::")]
    if not dids:
        sys.exit("HSK deck not found")
    q = ("SELECT c.queue,c.type,c.reps,n.tags FROM cards c JOIN notes n ON n.id=c.nid "
         f"WHERE c.did IN ({','.join('?'*len(dids))})")
    agg = defaultdict(lambda: [0, 0, 0])  # level -> [learned, todo, susp]
    for queue, type_, reps, tags in c.execute(q, dids):
        m = re.search(r"HSK::HSK(\d)", tags)
        lvl = f"HSK{m.group(1)}" if m else "chars"
        st = status_of(queue, type_, reps)
        agg[lvl][{2: 0, 1: 1, 0: 2}[st]] += 1
    order = ["HSK1", "HSK2", "HSK3", "HSK4", "HSK5", "HSK6", "HSK7", "chars"]
    rows = [(lvl, *agg[lvl]) for lvl in order if lvl in agg]
    print("HSK 3.0 — progress through the HSK deck (by card tag)\n")
    render(rows, "BAND")


def chart_20(db):
    """Map the whole collection onto the old HSK 2.0 word list."""
    if not os.path.exists(HSK20):
        sys.exit(f"missing {HSK20} (the HSK 2.0 word list)")
    hsk20 = json.load(open(HSK20))
    word2lvl = {}
    for w in hsk20:                              # lowest level wins (list is already deduped)
        word2lvl.setdefault(w["word"], w["level"])
    # best status per word across the WHOLE collection
    c = db.cursor()
    best = {}
    for sfld, queue, type_, reps in c.execute(
            "SELECT n.sfld,c.queue,c.type,c.reps FROM cards c JOIN notes n ON n.id=c.nid"):
        w = clean(sfld)
        if not w:
            continue
        st = status_of(queue, type_, reps)
        if best.get(w, -1) < st:
            best[w] = st
    agg = defaultdict(lambda: [0, 0, 0, 0])      # level -> [learned, todo, susp, absent]
    for word, lvl in word2lvl.items():
        st = best.get(word)
        if st is None:
            agg[lvl][3] += 1
        else:
            agg[lvl][{2: 0, 1: 1, 0: 2}[st]] += 1
    absent = sum(agg[l][3] for l in agg)
    print("HSK 2.0 — old-standard coverage, mapped from your whole collection\n")
    rows = [(f"HSK{l}", agg[l][0], agg[l][1], agg[l][2]) for l in range(1, 7)]
    render(rows, "OLD HSK")
    if absent:
        print(f"\n({absent} HSK 2.0 words are NOT in your collection at all)")
    else:
        print("\n(every HSK 2.0 word is present in your collection)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--standard", choices=["2.0", "3.0"], default="3.0")
    args = ap.parse_args()
    db, tmp = open_copy()
    try:
        (chart_20 if args.standard == "2.0" else chart_30)(db)
    finally:
        db.close()
        os.unlink(tmp)


if __name__ == "__main__":
    main()
