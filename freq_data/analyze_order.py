#!/usr/bin/env python3
"""Analyze hanly deck word ordering vs. corpus frequency (wordfreq)."""
import json, re, sys
from wordfreq import zipf_frequency, top_n_list

def clean(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    return s.strip()

# ── load deck notes ──
with open("quality/all_notes.json") as f:
    notes = json.load(f)
nid2word = {n["nid"]: clean(n.get("Simplified", "")) for n in notes}

# ── load queue order (nid, due) for NEW cards ──
queue = []  # (due, nid, word)
with open("freq_data/hanly_new_queue.tsv") as f:
    for line in f:
        nid_s, due_s = line.rstrip("\n").split("\t")
        nid = int(nid_s)
        w = nid2word.get(nid, "")
        if w:
            queue.append((int(due_s), nid, w))
queue.sort()  # ascending due = the order you'll encounter them

# ── zipf score per queued word ──
rows = []  # (position_index, due, word, zipf)
for i, (due, nid, w) in enumerate(queue):
    z = zipf_frequency(w, "zh")
    rows.append((i, due, w, z))

zips = [z for *_, z in rows]
n = len(rows)
print(f"=== QUEUE: {n} unstudied hanly words, in the order Anki will show them ===")
print(f"zipf range: {min(zips):.2f}..{max(zips):.2f} | zero-freq (not in corpus): {sum(1 for z in zips if z==0)}")

# Correlation: does later-in-queue == rarer? (we WANT a downward trend)
# Spearman-ish: compare avg zipf of first vs last fifths
fifth = n // 5
def avg(a): return sum(a)/len(a) if a else 0
print(f"avg zipf  first 20% of queue: {avg(zips[:fifth]):.2f}")
print(f"avg zipf   last 20% of queue: {avg(zips[-fifth:]):.2f}")
print("(optimal = first chunk noticeably higher than last chunk)\n")

# ── GOAL A: inversions — common words stuck LATE in the queue ──
# A word is "buried" if it's high-frequency but sits in the back half of the queue.
buried = [(z, i, w) for (i, due, w, z) in rows if i > n*0.5 and z >= 4.5]
buried.sort(reverse=True)
print(f"=== A. BURIED COMMON WORDS: high-freq (zipf>=4.5) but in back half of queue ({len(buried)} total) ===")
print("   (you'll learn these LATE even though they're very common)")
for z, i, w in buried[:30]:
    print(f"   zipf {z:.2f}  queue#{i:>4}/{n}  {w}")

# ── also: rare words stuck EARLY (you'll learn obscure words too soon) ──
early_rare = [(z, i, w) for (i, due, w, z) in rows if i < n*0.3 and 0 < z < 3.0]
early_rare.sort()
print(f"\n=== A2. RARE WORDS SCHEDULED EARLY: zipf<3.0 in first 30% of queue ({len(early_rare)} total) ===")
for z, i, w in early_rare[:20]:
    print(f"   zipf {z:.2f}  queue#{i:>4}/{n}  {w}")
