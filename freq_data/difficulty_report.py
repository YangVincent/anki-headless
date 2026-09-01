#!/usr/bin/env python3
"""Estimate how hard a book is FOR VINCENT, using his real tap data (words he looked
up while reading) to calibrate a difficulty frontier on the wordfreq Zipf scale
(7=extremely common … 2=rare), then scoring the book's vocabulary against it.
Usage: difficulty_report.py <book.jsonl> "<book name>"

The scoring lives in tap_frontier() and score(), so a caller that ranks many texts
against one another uses the same definition this report prints.
"""
import sys, json, sqlite3, re
import jieba, jieba.posseg as pseg
from wordfreq import zipf_frequency
jieba.initialize()

DONG = "/home/vincent/chinese-projects/dong-chinese/server/dongchinese.db"
HAN = re.compile(r"[一-鿿]")
PROPER = {"弗恩", "夏洛", "威尔伯", "朱克曼", "坦普尔顿", "霍默", "勒维", "阿拉布尔",
          "艾弗里", "怀特", "任溶溶"}


def z(w):
    return zipf_frequency(w, "zh")


def tap_frontier():
    """Vincent's lookup frontier: the median Zipf of the words he taps while reading.
    Words rarer than this are the lookup zone. Returns (frontier, tapped word counts)."""
    c = sqlite3.connect(f"file:{DONG}?mode=ro", uri=True)
    tapped = {}
    for w, n in c.execute("SELECT word, COUNT(*) FROM reading_events "
                          "WHERE kind IN ('tap','save') AND word IS NOT NULL GROUP BY word"):
        if w and HAN.search(w):
            tapped[w] = n
    tap_z = sorted(z(w) for w in tapped if len(w) >= 2 and z(w) > 0)
    frontier = tap_z[len(tap_z) // 2] if tap_z else 3.5
    return frontier, tapped, len(tap_z)


def score(text, pages, tapped, frontier, proper=PROPER):
    """Tokenize one text, drop proper nouns, and score its vocabulary load."""
    content = [t for t, flag in pseg.cut(text)
               if len(t) >= 2 and HAN.search(t)
               and not flag.startswith(("nr", "ns", "nt", "nz")) and t not in proper]
    uniq = {}
    for t in content:
        uniq[t] = uniq.get(t, 0) + 1
    tot = len(content)
    firm_tok = sum(n for w, n in uniq.items() if 0 < z(w) < 3.0)   # genuinely uncommon
    lookup = {w: n for w, n in uniq.items()
              if (0 < z(w) < frontier) or (w in tapped and z(w) < 4.2)}
    lookup_tok = sum(lookup.values())
    firm_pct = 100 * firm_tok / max(tot, 1)
    lookup_pct = 100 * lookup_tok / max(tot, 1)
    return {
        "tokens": tot, "unique": len(uniq), "pages": pages, "uniq": uniq,
        "lookup": lookup, "tapped_here": [w for w in uniq if w in tapped],
        "firm_tok": firm_tok, "lookup_tok": lookup_tok,
        "firm_pct": firm_pct, "lookup_pct": lookup_pct,
        # blend the firm floor (Zipf<3) and the frontier ceiling for an honest effective load
        "effective": (firm_pct + lookup_pct) / 2,
        "cov": {zmin: 100 * sum(n for w, n in uniq.items() if z(w) >= zmin) / max(tot, 1)
                for zmin in (4.5, 4.0, 3.5, 3.0)},
    }


def band(d):
    return ("very comfortable — extensive reading" if d < 5 else
            "light-intermediate — easy grammar, some vocab lookups" if d < 12 else
            "intermediate — easy sentences but a real vocab load" if d < 22 else
            "hard — intensive reading")


def main():
    book_jsonl = sys.argv[1]
    book_name = sys.argv[2] if len(sys.argv) > 2 else "the book"
    frontier, tapped, n_tap = tap_frontier()
    lines = [ln for ln in open(book_jsonl, encoding="utf-8", errors="ignore") if ln.strip()]
    text = "\n".join(json.loads(ln).get("text", "") for ln in lines)
    # A traditional source scores as almost entirely rare against a simplified corpus.
    from anki_coverage import looks_traditional
    if looks_traditional(text):
        print("WARNING: this text is traditional. Convert it to simplified first, or "
              "every count below is wrong.", file=sys.stderr)
    r = score(text, len(lines), tapped, frontier)
    pages = max(r["pages"], 1)

    print(f"=== Difficulty of 《{book_name}》 for you ===")
    print(f"analyzed: {r['pages']} pages, {r['tokens']:,} content-word tokens "
          f"(names excluded), {r['unique']:,} unique")
    print(f"your lookup frontier: Zipf ~{frontier:.2f} (median of {n_tap} words you've looked up)")
    print()
    print("vocabulary coverage by commonness (Zipf; higher=easier):")
    print(f"  very common (≥4.5): {r['cov'][4.5]:.0f}%   common (≥4.0): {r['cov'][4.0]:.0f}%   "
          f"mid (≥3.5): {r['cov'][3.5]:.0f}%   incl. uncommon (≥3.0): {r['cov'][3.0]:.0f}%")
    print()
    print(f"firm lookup load (genuinely uncommon, Zipf<3.0): {r['firm_pct']:.1f}%  "
          f"(~{r['firm_tok']/pages:.1f}/page)")
    print(f"frontier estimate (at/below your level ~{frontier:.1f}): {r['lookup_pct']:.1f}%  "
          f"(~{r['lookup_tok']/pages:.1f}/page)")
    print(f"words you've already tapped that recur here: {len(r['tapped_here'])}  "
          f"({', '.join(r['tapped_here'][:10])})")
    top = sorted(r["lookup"].items(), key=lambda x: -x[1])[:22]
    print("top lookup candidates:")
    print("  " + "  ".join(f"{w}×{n}" for w, n in top))
    print(f"\nVERDICT: {band(r['effective'])}  (effective lookup ~{r['effective']:.0f}%)")


if __name__ == "__main__":
    main()
