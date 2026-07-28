#!/usr/bin/env python3
"""Photographed, underlined book page -> study table + known-set calibration.

Vincent photographs pages he's marked up. Claude reads the underlines off the photo
and passes them here IN PAGE ORDER. This tool then:

  1. Lists the marked words IN PAGE ORDER with pinyin, definition, and how often each
     recurs in the whole book — the recurrence verdict is what decides study value:
        SUBSTANTIAL (10+)  card it, the book will drill it
        middling    (3-9)  worth a look
        disregard   (0-2)  scenery; 膻腥 appears once in 168k characters
  2. Harvests calibration for the known-set:

        marked                        -> NOT SOLID YET (his words: doesn't know it well
                                         enough, or is unsure of usage). Overrides every
                                         other source — a marked word is never "known".
        visible on the page (--seen),
        not marked, currently counted
        as unknown                    -> PRESUMED KNOWN (he read past it)

Why (2) matters: every difficulty number is computed against a known-set of ~3,500
words (Anki known_words + HSK1-3 + Hanly). His real reading vocabulary is far larger,
just unrecorded — so "words you don't know" lists get polluted with 听到 / 来到 / 看着.
Each page retires a batch of those false unknowns.

The presumed-known list comes ONLY from words visible in the photo. An earlier version
inferred the page by searching the book for "paragraphs containing >=2 marked words";
that was wrong — marks like 缓缓 (x124) matched paragraphs anywhere, and measurement
showed only 20-57% of matches were even in chapter 1, so it credited him with knowing
vocabulary from chapters he had never opened. Reading the page is the ground truth.

  page_marks.py --book "十日终焉·囚笼" --page 002 \
      --src /home/vincent/chinese-projects/ebooks/shiri_zhongyan_vol1.txt \
      --seen page_seen.json --marked 钨丝 悬 闪烁 ...      # marked in page order
  page_marks.py --show
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/home/vincent/chinese-projects/ebooks")
sys.path.insert(0, "/home/vincent/chinese-projects/dong-chinese/server")

STORE = Path("/home/vincent/anki-headless/reading_marks.json")
HAN = re.compile(r"[一-鿿]")
PROPER = ("nr", "ns", "nt", "nz")
# pypinyin picks the wrong reading for these; CC-CEDICT's gloss is a character-by-character
# fallback for these. Hand-corrected once, applied everywhere.
PY_FIX = {"散发": "sàn fā", "打量": "dǎ liang", "晕染": "yùn rǎn", "膻腥": "shān xīng"}
GLOSS_FIX = {"钨丝": "tungsten filament", "膻腥": "rank, gamey smell (of sheep/goat)",
             "嘀嗒": "tick-tock", "冚家铲": "(Cantonese) strong profanity",
             "粉肠": "(Cantonese) idiot, fool"}


def load():
    if STORE.exists():
        return json.loads(STORE.read_text(encoding="utf-8"))
    return {"sources": [], "marked_not_solid": [], "presumed_known": []}


def save(d):
    d["marked_not_solid"] = sorted(set(d["marked_not_solid"]))
    # anything he later marked must not linger on the presumed-known list
    d["presumed_known"] = sorted(set(d["presumed_known"]) - set(d["marked_not_solid"]))
    STORE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book"); ap.add_argument("--page")
    ap.add_argument("--src"); ap.add_argument("--marked", nargs="*", default=[])
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--no-store", action="store_true", help="report only, don't record")
    # Locating the photographed page by "paragraphs containing >=2 marked words" searches
    # the WHOLE book, and marks like 缓缓 (x124) or 此时 (x95) match paragraphs hundreds of
    # pages away. Measured: only 20-57% of matches were even in chapter 1, so most
    # "presumed known" words came from text he has never read — evidence of nothing.
    # Scoping the search to the chapters he has actually reached fixes it.
    ap.add_argument("--seen", help="JSON of the words visible on the page "
                                   "({page: [words]} or a bare list) — the calibration source")
    ap.add_argument("--drop-inferred", action="store_true",
                    help="wipe presumed_known (the old book-search guesses) and start clean")
    a = ap.parse_args()

    d = load()
    if a.show:
        print(f"{len(d['sources'])} pages logged")
        for s in d["sources"]:
            print(f"  {s['book']} p{s['page']}: {len(s['marked'])} marked, "
                  f"{len(s['presumed_known'])} presumed known")
        print(f"\nmarked (not solid): {len(d['marked_not_solid'])}")
        print(f"presumed known:     {len(d['presumed_known'])}")
        return

    import jieba.posseg as pseg
    import report_data as RD
    hskw, hskc, hsk123, ced = RD.load_maps()
    con = sqlite3.connect("/home/vincent/chinese-projects/dong-chinese/server/dongchinese.db")
    known_words, _ = RD.known_sets(con, hsk123)

    text = Path(a.src).read_text(encoding="utf-8")
    counts = Counter(w for w in __import__("jieba").cut(text) if HAN.search(w))
    marked = list(dict.fromkeys(a.marked))          # keep page order, drop dupes

    py = lambda w: PY_FIX.get(w) or RD.py(w)
    gl = lambda w: GLOSS_FIX.get(w) or RD.gloss(w, ced)[:42]

    # Recurrence decides whether a word is worth a card. A word marked because the usage
    # felt shaky is still only worth studying if the book will drill it again.
    def verdict(n):
        return "SUBSTANTIAL" if n >= 10 else "middling" if n >= 3 else "disregard"

    print(f"\n{'='*94}\nPAGE {a.page}  ·  {a.book}  ·  {len(marked)} words marked\n{'='*94}")
    print(f"{'#':<4}{'word':<11}{'pinyin':<17}{'×book':>6}  {'recurrence':<13} definition")
    print("-" * 94)
    for i, w in enumerate(marked, 1):
        n = counts.get(w, 0)
        print(f"{i:<4}{w:<11}{py(w):<17}{n:>6}  {verdict(n):<13} {gl(w)}")

    tally = Counter(verdict(counts.get(w, 0)) for w in marked)
    print(f"\n  {tally['SUBSTANTIAL']} substantial (10+ uses — card these) · "
          f"{tally['middling']} middling (3-9) · {tally['disregard']} disregard (0-2)")

    # --- calibration ---
    # The words he read past are taken from the PHOTO (--seen), never inferred by
    # searching the book. The old approach located the page by "paragraphs containing
    # >=2 marked words", but marks like 缓缓 (x124) match paragraphs anywhere: measured,
    # only 20-57% of matches were even in chapter 1, so it was crediting him with
    # knowing words from chapters he has never opened. Reading the page is the ground
    # truth — no inference needed.
    presumed = []
    if a.seen:
        seen = json.loads(Path(a.seen).read_text(encoding="utf-8"))
        words = seen[a.page] if isinstance(seen, dict) else seen
        presumed = sorted({w for w in words
                           if w not in known_words and w not in marked and len(w) >= 2})
        print(f"\ncalibration: {len(words)} words visible on the page, "
              f"{len(presumed)} of them the model wrongly counts as unknown")
    else:
        print("\ncalibration: skipped (pass --seen with the words visible on the page)")

    if not a.no_store:
        d["sources"] = [s for s in d["sources"] if not (s["book"] == a.book and s["page"] == a.page)]
        d["sources"].append({"book": a.book, "page": a.page,
                             "marked": marked, "presumed_known": presumed})
        d["marked_not_solid"] = sorted(set(d["marked_not_solid"]) | set(marked))
        d["presumed_known"] = sorted(set(d["presumed_known"]) | set(presumed))
        save(d)
        print(f"store: {len(d['marked_not_solid'])} marked, "
              f"{len(d['presumed_known'])} presumed known, {len(d['sources'])} pages")


if __name__ == "__main__":
    main()
