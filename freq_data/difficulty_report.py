#!/usr/bin/env python3
"""Estimate how hard a book is FOR VINCENT, using his real tap data (words he looked
up while reading) to calibrate a difficulty frontier on the wordfreq Zipf scale
(7=extremely common … 2=rare), then scoring the book's vocabulary against it.
Usage: difficulty_report.py <book.jsonl> "<book name>" """
import sys, json, sqlite3, re
import jieba, jieba.posseg as pseg
from wordfreq import zipf_frequency
jieba.initialize()

DONG = "/home/vincent/chinese-projects/dong-chinese/server/dongchinese.db"
book_jsonl = sys.argv[1]
book_name = sys.argv[2] if len(sys.argv) > 2 else "the book"
HAN = re.compile(r"[一-鿿]")
PROPER = {"弗恩", "夏洛", "威尔伯", "朱克曼", "坦普尔顿", "霍默", "勒维", "阿拉布尔",
          "艾弗里", "怀特", "任溶溶"}
def z(w): return zipf_frequency(w, "zh")

# --- Vincent's tap frontier ---
c = sqlite3.connect(f"file:{DONG}?mode=ro", uri=True)
tapped = {}
for w, n in c.execute("SELECT word, COUNT(*) FROM reading_events WHERE kind IN ('tap','save') AND word IS NOT NULL GROUP BY word"):
    if w and HAN.search(w):
        tapped[w] = n
tap_z = sorted(z(w) for w in tapped if len(w) >= 2 and z(w) > 0)
# median Zipf of the words he looks up = his frontier; words rarer than this are lookup-zone.
frontier = tap_z[len(tap_z) // 2] if tap_z else 3.5

# --- tokenize the book, drop proper nouns ---
text = "\n".join(json.loads(ln).get("text", "") for ln in open(book_jsonl, encoding="utf-8", errors="ignore") if ln.strip())
content = [t for t, flag in pseg.cut(text)
           if len(t) >= 2 and HAN.search(t) and not flag.startswith(("nr", "ns", "nt", "nz")) and t not in PROPER]
uniq = {}
for t in content: uniq[t] = uniq.get(t, 0) + 1
tot = len(content)
pages = sum(1 for _ in open(book_jsonl, encoding="utf-8", errors="ignore"))

def cov(zmin): return 100 * sum(n for w, n in uniq.items() if z(w) >= zmin) / max(tot, 1)
firm_tok = sum(n for w, n in uniq.items() if 0 < z(w) < 3.0)      # genuinely uncommon = firm lookups
# frontier estimate: below his tap frontier, or a word he's tapped (but not common confirm-taps)
lookup = {w: n for w, n in uniq.items()
          if (0 < z(w) < frontier) or (w in tapped and z(w) < 4.2)}
lookup_tok = sum(lookup.values())
tapped_here = [w for w in uniq if w in tapped]

print(f"=== Difficulty of 《{book_name}》 for you ===")
print(f"analyzed: {pages} pages, {tot:,} content-word tokens (names excluded), {len(uniq):,} unique")
print(f"your lookup frontier: Zipf ~{frontier:.2f} (median of {len(tap_z)} words you've looked up)")
print()
print("vocabulary coverage by commonness (Zipf; higher=easier):")
print(f"  very common (≥4.5): {cov(4.5):.0f}%   common (≥4.0): {cov(4.0):.0f}%   "
      f"mid (≥3.5): {cov(3.5):.0f}%   incl. uncommon (≥3.0): {cov(3.0):.0f}%")
print()
print(f"firm lookup load (genuinely uncommon, Zipf<3.0): {100*firm_tok/max(tot,1):.1f}%  (~{firm_tok/max(pages,1):.1f}/page)")
print(f"frontier estimate (at/below your level ~{frontier:.1f}): {100*lookup_tok/max(tot,1):.1f}%  (~{lookup_tok/max(pages,1):.1f}/page)")
print(f"words you've already tapped that recur here: {len(tapped_here)}  ({', '.join(tapped_here[:10])})")
top = sorted(lookup.items(), key=lambda x: -x[1])[:22]
print("top lookup candidates:")
print("  " + "  ".join(f"{w}×{n}" for w, n in top))
# blend the firm floor (Zipf<3) and the frontier ceiling for an honest effective load
d = (100 * firm_tok / max(tot, 1) + 100 * lookup_tok / max(tot, 1)) / 2
band = ("very comfortable — extensive reading" if d < 5 else
        "light-intermediate — easy grammar, some vocab lookups" if d < 12 else
        "intermediate — easy sentences but a real vocab load" if d < 22 else
        "hard — intensive reading")
print(f"\nVERDICT: {band}  (effective lookup ~{d:.0f}%)")
