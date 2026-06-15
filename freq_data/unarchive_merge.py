#!/usr/bin/env python3
"""Build the unified 'Vocab' deck:
  1. move hanly forward (ord0) cards -> Vocab
  2. unsuspend + move the best archive ord0 card for each zipf>=3.5 target word
     not already active (dedup: one active card per word)
  3. reposition all Vocab new cards by frequency (most common first)
Dry-run by default; pass --apply to write. Forward (recognition) cards only;
reverse/production cards are left untouched (deferred).
"""
import re, sys, collections
from anki.collection import Collection
from wordfreq import zipf_frequency, top_n_list

COLLECTION="/home/vincent/anki-headless/collection.anki2"
HANLY_DID=1770350587056
APPLY="--apply" in sys.argv

def clean(s): return re.sub(r"<[^>]+>","",s or "").strip()

# ── CEDICT (real-word + proper-noun filter) ──
ced={}
with open("/home/vincent/dong-chinese/Resources/cedict_ts.u8") as f:
    for line in f:
        if line.startswith("#"): continue
        m=re.match(r"(\S+) (\S+) \[([^\]]*)\] /(.+)/",line)
        if m and m.group(2) not in ced: ced[m.group(2)]=(m.group(3),m.group(4))
POL=re.compile(r"\b(Party|committee|CCP|Communist|Politburo|PRC|People..s Republic|peoples? |government|court|electoral|constituency|cadre|propaganda|secretary \(of|standing committee|military (district|region)|province|provincial|prefecture|township|administrative|PLA|socialis|dictatorship|constitutional gov)\b",re.I)
def target_word(w):
    if w not in ced or ced[w][0][:1].isupper(): return False
    if POL.search(ced[w][1]) or w[-1:]=='委' or w.endswith('政府') or w.endswith('书记'): return False
    return len(w)>=2 and re.fullmatch(r'[一-鿿]+',w) is not None
TARGET=set(w for w in top_n_list("zh",60000) if zipf_frequency(w,"zh")>=3.5 and target_word(w))
print(f"target words (zipf>=3.5 clean): {len(TARGET):,}")

col=Collection(COLLECTION)
try:
    nt={m['id']:{f['name']:i for i,f in enumerate(m['flds'])} for m in col.models.all()}
    SEP=chr(31)
    def field(flds,mid,name):
        idx=nt[mid].get(name);
        return clean(flds.split(SEP)[idx]) if idx is not None and idx < len(flds.split(SEP)) else ""

    # words already ACTIVE via hanly forward (ord0) cards -> keep these
    active_words=set(); hanly_fwd_cids=[]
    for cid,nid in col.db.all("SELECT id,nid FROM cards WHERE did=? AND ord=0",HANLY_DID):
        mid,flds=col.db.first("SELECT mid,flds FROM notes WHERE id=?",nid)
        w=field(flds,mid,"Simplified")
        if w: active_words.add(w)
        hanly_fwd_cids.append(cid)
    print(f"hanly forward cards -> Vocab: {len(hanly_fwd_cids):,} ({len(active_words):,} distinct words)")

    # scan Archive::Words ord0 cards; pick best note per target word not already active
    arch_did=col.decks.id_for_name("Archive::Words")
    best={}  # word -> (richness, cid)
    rows=col.db.all("SELECT c.id,c.nid FROM cards c WHERE c.did=? AND c.ord=0",arch_did)
    for cid,nid in rows:
        mid,flds=col.db.first("SELECT mid,flds FROM notes WHERE id=?",nid)
        w=field(flds,mid,"Simplified")
        if not w or w in active_words or w not in TARGET: continue
        rich=sum(1 for k in ("Pinyin","Meaning","SentenceSimplified","Audio") if field(flds,mid,k))
        if w not in best or rich>best[w][0]: best[w]=(rich,cid)
    arch_cids=[cid for _,cid in best.values()]
    print(f"archive words to unsuspend+move -> Vocab: {len(arch_cids):,}")
    covered=len(active_words & TARGET)+len(best)
    print(f"target coverage after merge: {covered:,}/{len(TARGET):,}  | gaps left to generate: {len(TARGET)-covered:,}")

    if not APPLY:
        print("\nDRY-RUN (no changes). Re-run with --apply to execute.")
    else:
        vocab_did=col.decks.id(" Vocab".strip())  # create/get 'Vocab'
        # move hanly forward cards
        col.set_deck(hanly_fwd_cids, vocab_did)
        # unsuspend + move archive cards
        col.sched.unsuspend_cards(arch_cids)
        col.set_deck(arch_cids, vocab_did)
        # reposition all Vocab NEW cards (ord0,type0) by frequency desc
        newrows=col.db.all("SELECT c.id,c.nid FROM cards c WHERE c.did=? AND c.type=0",vocab_did)
        order=[]
        for cid,nid in newrows:
            mid,flds=col.db.first("SELECT mid,flds FROM notes WHERE id=?",nid)
            w=field(flds,mid,"Simplified")
            order.append((zipf_frequency(w,"zh") if w else 0.0, cid))
        order.sort(key=lambda x:-x[0])
        col.sched.reposition_new_cards([cid for _,cid in order],starting_from=1,step_size=1,randomize=False,shift_existing=False)
        print(f"\nAPPLIED: Vocab deck now has {len(newrows):,} new cards, reposition by frequency done.")
finally:
    col.close()
