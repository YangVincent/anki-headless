#!/usr/bin/env python3
"""Build the leverage-ordered list of single characters that are in Vincent's
Vocab deck words but NOT in Hanly (june_hanly.json). High-value head only:
keep chars that appear in at least one Zipf>4.5 deck word.
Read-only on the collection (uses a copy). Writes freq_data/chars/gap_chars.json.
Usage: gap_build.py [--cutoff 4.5]
"""
import sqlite3, json, collections, re, sys, shutil, os
from wordfreq import zipf_frequency
from pypinyin import pinyin, Style

ROOT = "/home/vincent/anki-headless"
VOCAB_DID = 1781536737704
CUTOFF = 4.5
if "--cutoff" in sys.argv:
    CUTOFF = float(sys.argv[sys.argv.index("--cutoff") + 1])

# read collection via a copy (never touch the live file)
src = f"{ROOT}/collection.anki2"
tmp = "/tmp/col_gap_read.anki2"
shutil.copy(src, tmp)
c = sqlite3.connect(tmp)
rows = c.execute(
    "select distinct n.flds from cards cd join notes n on n.id=cd.nid where cd.did=?",
    (VOCAB_DID,),
).fetchall()
words = [flds.split(chr(31))[0].strip() for (flds,) in rows]
words = [w for w in words if w]

hanly = set(json.load(open(f"{ROOT}/june_hanly.json")).keys())

# CEDICT single-char lookup for pinyin/meaning/trad.
# Aggregate ALL senses per char, then prefer substantive glosses over
# surname/variant/abbr-only entries (CEDICT often lists those first).
ced_raw = collections.defaultdict(list)  # simp -> [(trad, [senses])]
with open("/home/vincent/chinese-projects/dong-chinese/Resources/cedict_ts.u8") as f:
    for line in f:
        if line.startswith("#"):
            continue
        m = re.match(r"(\S+) (\S+) \[([^\]]*)\] /(.+)/", line)
        if m and len(m.group(2)) == 1:
            senses = [s for s in m.group(4).split("/") if s]
            ced_raw[m.group(2)].append((m.group(1), senses))

def best_gloss(ch):
    if ch not in ced_raw:
        return (ch, "")
    trad = ced_raw[ch][0][0]
    senses = [s for _, ss in ced_raw[ch] for s in ss]
    skip = lambda s: bool(re.match(r"(surname |variant of|old variant|abbr\.? for|see )", s, re.I))
    good = [s for s in senses if not skip(s)] or senses
    # dedupe preserving order
    seen, uniq = set(), []
    for s in good:
        if s not in seen:
            seen.add(s); uniq.append(s)
    return (trad, "; ".join(uniq)[:80])

ced = {ch: best_gloss(ch) for ch in ced_raw}

def han_chars(w):
    return [ch for ch in w if "一" <= ch <= "鿿"]

words_hi = collections.Counter()  # # of zipf>CUTOFF words containing the char
words_all = collections.Counter()
zmax = collections.defaultdict(float)
examples = collections.defaultdict(list)
for w in words:
    z = zipf_frequency(w, "zh")
    for ch in set(han_chars(w)):
        if ch in hanly:
            continue
        words_all[ch] += 1
        zmax[ch] = max(zmax[ch], z)
        if z > CUTOFF:
            words_hi[ch] += 1
            if len(examples[ch]) < 5:
                examples[ch].append((w, round(z, 2)))

# high-value head: char appears in >=1 zipf>CUTOFF word
head = [ch for ch in words_all if words_hi[ch] >= 1]
# leverage order: most high-freq words first, then highest single-word zipf
head.sort(key=lambda ch: (-words_hi[ch], -zmax[ch], -words_all[ch]))

out = []
for rank, ch in enumerate(head):
    trad, gloss = ced.get(ch, (ch, ""))
    py = pinyin(ch, style=Style.TONE)[0][0]
    out.append({
        "rank": rank,
        "char": ch,
        "pinyin": py,
        "meaning": gloss[:80],
        "trad": trad,
        "words_hi": words_hi[ch],
        "words_all": words_all[ch],
        "maxZ": round(zmax[ch], 2),
        "examples": sorted(examples[ch], key=lambda x: -x[1]),
    })

os.makedirs(f"{ROOT}/freq_data/chars", exist_ok=True)
json.dump(out, open(f"{ROOT}/freq_data/chars/gap_chars.json", "w"),
          ensure_ascii=False, indent=1)
print(f"cutoff Zipf>{CUTOFF}: {len(out)} not-in-Hanly chars (high-value head)")
print("top 20 by leverage:")
for o in out[:20]:
    ex = " ".join(f"{w}({z})" for w, z in o["examples"][:3])
    print(f"  {o['rank']:>3} {o['char']}  {o['pinyin']:<6} hiWords={o['words_hi']:<3} maxZ={o['maxZ']}  {ex}")
print(f"\nwrote freq_data/chars/gap_chars.json")
