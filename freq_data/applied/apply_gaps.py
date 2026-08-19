#!/usr/bin/env python3
"""Create gap-word cards in the Vocab deck: new ChineseVocabulary notes with
CEDICT pinyin/meaning/traditional + generated sentence (bold + cloze). Reverse
(ord1) card suspended. Then reposition Vocab new cards by frequency. Inline verify.
Dry-run unless --apply. Run via anki_op.sh."""
import json, glob, re, sys
from anki.collection import Collection
from wordfreq import zipf_frequency, top_n_list

ROOT="/home/vincent/anki-headless"
APPLY="--apply" in sys.argv
def bold(s,w): return s.replace(w,f"<b>{w}</b>",1) if w in s else s
def cloze(s,w): return s.replace(w,"[ ]",1) if w in s else s

inp={d["word"]:d for d in json.load(open(f"{ROOT}/freq_data/gen_gaps/gap_input.json"))}
sent={}
for f in glob.glob(f"{ROOT}/freq_data/gen_gaps/out_batch_*.json"):
    for e in json.load(open(f)): sent[e["word"]]=e
# frequency rank for the Frequency field
rank={w:i+1 for i,w in enumerate(top_n_list("zh",60000))}

todo=[w for w in inp if w in sent and sent[w].get("sent_simp") and w in sent[w]["sent_simp"]]

col=Collection(f"{ROOT}/collection.anki2")
try:
    cv=next(m for m in col.models.all() if m["name"]=="ChineseVocabulary")
    fi={f["name"]:i for i,f in enumerate(cv["flds"])}
    vd=col.decks.id_for_name("Vocab")
    existing=set()
    SEP=chr(31)
    for nid in col.db.list("SELECT DISTINCT nid FROM cards WHERE did=?",vd):
        mid,flds=col.db.first("SELECT mid,flds FROM notes WHERE id=?",nid)
        existing.add(flds.split(SEP)[0].strip())
    todo=[w for w in todo if w not in existing]
    print(f"gap cards to create: {len(todo)}")
    created=0; new_nids=[]
    if APPLY:
        for w in todo:
            d=inp[w]; s=sent[w]
            note=col.new_note(cv)
            note.fields[fi["Simplified"]]=w
            note.fields[fi["Traditional"]]=d.get("trad",w)
            note.fields[fi["Pinyin"]]=d["pinyin"]
            note.fields[fi["Meaning"]]=d["gloss"]
            if "Frequency" in fi: note.fields[fi["Frequency"]]=str(rank.get(w,""))
            note.fields[fi["SentenceSimplified"]]=bold(s["sent_simp"],w)
            note.fields[fi["SentenceTraditional"]]=bold(s.get("sent_trad",""),d.get("trad",w))
            note.fields[fi["SentenceSimplifiedCloze"]]=cloze(s["sent_simp"],w)
            note.fields[fi["SentenceTraditionalCloze"]]=cloze(s.get("sent_trad",""),d.get("trad",w))
            note.fields[fi["SentencePinyin"]]=s.get("pinyin","")
            note.fields[fi["SentenceMeaning"]]=s.get("english","")
            col.add_note(note,vd); new_nids.append(note.id); created+=1
        # suspend the reverse (ord1) cards of the new notes
        rev=col.db.list("SELECT id FROM cards WHERE nid IN (%s) AND ord=1"%",".join(map(str,new_nids)))
        col.sched.suspend_cards(rev)
        # reposition all Vocab new (ord0,type0) cards by frequency
        newcards=col.db.all("SELECT c.id,c.nid FROM cards c WHERE c.did=? AND c.type=0 AND c.ord=0",vd)
        order=[]
        for cid,nid in newcards:
            mid,flds=col.db.first("SELECT mid,flds FROM notes WHERE id=?",nid)
            w=re.sub(r"<[^>]+>","",flds.split(SEP)[0]).strip()
            order.append((zipf_frequency(w,"zh") if w else 0.0,cid))
        order.sort(key=lambda x:-x[0])
        col.sched.reposition_new_cards([c for _,c in order],starting_from=1,step_size=1,randomize=False,shift_existing=False)
        print(f"APPLIED: created {created} cards, suspended {len(rev)} reverse, repositioned {len(newcards)} new cards")
        # verify
        tot=col.db.scalar("SELECT COUNT(*) FROM cards WHERE did=? AND type=0 AND ord=0",vd)
        print(f"verify: Vocab forward new-card queue now {tot}")
    else:
        print("DRY-RUN (no changes).")
finally:
    col.close()
