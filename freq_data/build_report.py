#!/usr/bin/env python3
"""Build read-only deliverables: full per-card report + missing-common-words import list."""
import json, re, csv
from wordfreq import zipf_frequency, top_n_list

def clean(s): return re.sub(r"<[^>]+>", "", s or "").strip()

# ── CEDICT: simplified -> (pinyin, gloss) ──
ced = {}
with open("/home/vincent/chinese-projects/dong-chinese/Resources/cedict_ts.u8") as f:
    for line in f:
        if line.startswith("#"): continue
        m = re.match(r"(\S+) (\S+) \[([^\]]*)\] /(.+)/", line)
        if m:
            simp, pin, gloss = m.group(2), m.group(3), m.group(4)
            if simp not in ced:
                ced[simp] = (pin, gloss.replace("/", "; "))

# ── deck notes ──
with open("quality/all_notes.json") as f:
    notes = json.load(f)
nid2note = {n["nid"]: n for n in notes}
deck_words = set(clean(n.get("Simplified","")) for n in notes); deck_words.discard("")

# ── card metadata ──
TYPE = {0:"new",1:"learning",2:"review",3:"relearn"}
cards = []  # (cid,nid,type,queue,due)
with open("freq_data/hanly_cards.tsv") as f:
    for line in f:
        cid,nid,t,q,due = (int(x) for x in line.split("\t"))
        cards.append((cid,nid,t,q,due))

# new-card queue order (type==0) -> position index
new_cards = sorted([c for c in cards if c[2]==0], key=lambda c:c[4])
nid_qpos = {}
for i,(cid,nid,t,q,due) in enumerate(new_cards):
    nid_qpos[nid] = i

# ── FULL REPORT CSV ──
with open("freq_data/REPORT_per_card.csv","w",newline="") as f:
    w = csv.writer(f)
    w.writerow(["cid","nid","simplified","pinyin","zipf","state","queue_pos_current","flag"])
    rows=[]
    for cid,nid,t,q,due in cards:
        note = nid2note.get(nid,{})
        word = clean(note.get("Simplified",""))
        z = zipf_frequency(word,"zh") if word else 0.0
        state = TYPE.get(t,"?")
        qpos = nid_qpos.get(nid,"") if t==0 else ""
        flag=""
        if t==0 and word:
            if z>=4.5 and isinstance(qpos,int) and qpos>len(new_cards)*0.5: flag="BURIED_COMMON"
            elif 0<z<2.0: flag="RARE_IDIOM_JUNK"
            elif z==0: flag="ZERO_FREQ"
            elif 0<z<3.0 and isinstance(qpos,int) and qpos<len(new_cards)*0.3: flag="RARE_EARLY"
        rows.append([cid,nid,word,clean(note.get("Pinyin","")),f"{z:.2f}",state,qpos,flag])
    rows.sort(key=lambda r:(r[5]!="new", float(r[4])), reverse=False)
    w.writerows(rows)
print(f"wrote freq_data/REPORT_per_card.csv ({len(cards)} cards)")

# ── MISSING COMMON WORDS import list ──
def is_real(x): return len(x)>=2 and re.fullmatch(r"[一-鿿]+", x)
top = [x for x in top_n_list("zh", 6000) if is_real(x)]
missing = [x for x in top if x not in deck_words]
with open("freq_data/MISSING_common_words.csv","w",newline="") as f:
    w = csv.writer(f)
    w.writerow(["rank_among_missing","simplified","zipf","pinyin","meaning_cedict","in_cedict"])
    for i,word in enumerate(missing,1):
        pin,gloss = ced.get(word,("",""))
        w.writerow([i,word,f"{zipf_frequency(word,'zh'):.2f}",pin,gloss[:120],"yes" if word in ced else "no"])
print(f"wrote freq_data/MISSING_common_words.csv ({len(missing)} words)")
print(f"  of which {sum(1 for x in missing if x in ced)} have CEDICT pinyin+meaning ready for import")
