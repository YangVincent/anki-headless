#!/usr/bin/env python3
import json, re
from wordfreq import zipf_frequency, top_n_list

def clean(s): return re.sub(r"<[^>]+>", "", s or "").strip()

with open("quality/all_notes.json") as f:
    notes = json.load(f)
deck_words = set(clean(n.get("Simplified","")) for n in notes)
deck_words.discard("")

learned = set()
with open("freq_data/hanly_learned.tsv") as f:
    learned_nids = set(int(x) for x in f.read().split() if x)
nid2word = {n["nid"]: clean(n.get("Simplified","")) for n in notes}
learned_words = set(nid2word[n] for n in learned_nids if n in nid2word)

# ── GOAL B: common words MISSING from deck ──
# Top frequent multi-char words (skip single chars + pure punctuation/latin/digits)
def is_real(w):
    return len(w) >= 2 and re.fullmatch(r"[一-鿿]+", w)
top = [w for w in top_n_list("zh", 6000) if is_real(w)]
missing = [w for w in top if w not in deck_words]
print(f"=== B. COMMON WORDS MISSING FROM YOUR DECK ===")
print(f"Of the top {len(top)} most-common multi-char words, {len(missing)} are NOT in your deck.")
print("Most-common 40 you're missing (zipf):")
for w in missing[:40]:
    print(f"   zipf {zipf_frequency(w,'zh'):.2f}  {w}")

# coverage by frequency band
def coverage(words):
    have = sum(1 for w in words if w in deck_words)
    return have, len(words), 100*have/len(words)
print("\nCoverage of top-frequency words by your deck:")
for k in (500, 1000, 2000, 3000, 6000):
    band = top[:k] if k<=len(top) else top
    h,t,p = coverage([w for w in top[:k]])
    print(f"   top {k:>4} words: {h}/{t} in deck ({p:.0f}%)")

# ── GOAL C: rare / junk cards in deck ──
scored = [(zipf_frequency(w,"zh"), w) for w in deck_words]
rare = sorted(scored)
zero = [w for z,w in rare if z==0]
print(f"\n=== C. RARE / LOW-VALUE CARDS IN DECK ===")
print(f"Cards with zipf==0 (word not in 334k corpus at all): {len(zero)}")
print("   sample:", " ".join(zero[:30]))
print("Lowest non-zero frequency cards (zipf<2.0):")
low = [(z,w) for z,w in rare if 0<z<2.0]
print(f"   count: {len(low)}")
for z,w in low[:25]:
    print(f"   zipf {z:.2f}  {w}")

# ── what you've ALREADY learned: is it well chosen? ──
lz = sorted(zipf_frequency(w,"zh") for w in learned_words if w)
if lz:
    print(f"\n=== D. ALREADY-LEARNED words ({len(learned_words)}) frequency profile ===")
    import statistics
    print(f"   median zipf {statistics.median(lz):.2f}, mean {statistics.mean(lz):.2f}")
    print(f"   how many are top-2000 common: {sum(1 for w in learned_words if w in set(top[:2000]))}/{len(learned_words)}")
