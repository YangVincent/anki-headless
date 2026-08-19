#!/usr/bin/env python3
"""Add proper ChineseVocabulary cards to Vocab for the ~1027 fixed foreign words:
  - reuse_nosent: fill the generated sentence into the EXISTING CV note, unsuspend
    its forward card, move to Vocab.
  - gen_new: create a NEW CV note (CEDICT pinyin/meaning/trad + sentence), reverse suspended.
Then reposition Vocab by frequency. Inline verify. Dry-run unless --apply. Run via anki_op.sh."""
import json, glob, re, sys
from anki.collection import Collection
from wordfreq import zipf_frequency, top_n_list

ROOT="/home/vincent/anki-headless"
APPLY="--apply" in sys.argv
def bold(s,w): return s.replace(w,f"<b>{w}</b>",1) if w in s else s
def cloze(s,w): return s.replace(w,"[ ]",1) if w in s else s

fix=json.load(open(f"{ROOT}/freq_data/foreign_fix.json"))
inp={d["word"]:d for d in json.load(open(f"{ROOT}/freq_data/foreign_gen/gen_input.json"))}
sent={}
for f in glob.glob(f"{ROOT}/freq_data/foreign_gen/out_batch_*.json"):
    try:
        for e in json.load(open(f)): sent[e["word"]]=e
    except Exception: pass
rank={w:i+1 for i,w in enumerate(top_n_list("zh",60000))}
reuse_set=set(fix["reuse_nosent"]); new_set=set(fix["gen_new"])

col=Collection(f"{ROOT}/collection.anki2")
try:
    SEP=chr(31)
    cv=next(m for m in col.models.all() if m["name"]=="ChineseVocabulary")
    fi={f["name"]:i for i,f in enumerate(cv["flds"])}
    vd=col.decks.id_for_name("Vocab")
    def valid(w): return w in sent and sent[w].get("sent_simp") and w in sent[w]["sent_simp"]
    reuse=[w for w in reuse_set if valid(w)]
    new=[w for w in new_set if valid(w)]
    print(f"reuse_nosent ready: {len(reuse)}/{len(reuse_set)} | gen_new ready: {len(new)}/{len(new_set)}")
    filled=created=0; new_nids=[]
    if APPLY:
        for w in reuse:
            s=sent[w]
            nid=col.db.scalar("SELECT id FROM notes WHERE mid=? AND flds LIKE ?",cv["id"],w+SEP+"%")
            if not nid: continue
            note=col.get_note(nid)
            tw=re.sub(r"<[^>]+>","",note.fields[fi["Traditional"]]).strip() or w
            note.fields[fi["SentenceSimplified"]]=bold(s["sent_simp"],w)
            note.fields[fi["SentenceTraditional"]]=bold(s.get("sent_trad",""),tw)
            note.fields[fi["SentenceSimplifiedCloze"]]=cloze(s["sent_simp"],w)
            note.fields[fi["SentenceTraditionalCloze"]]=cloze(s.get("sent_trad",""),tw)
            note.fields[fi["SentencePinyin"]]=s.get("pinyin","")
            note.fields[fi["SentenceMeaning"]]=s.get("english","")
            col.update_note(note)
            cid=col.db.scalar("SELECT id FROM cards WHERE nid=? AND ord=0",nid)
            if col.db.scalar("SELECT queue FROM cards WHERE id=?",cid)==-1:
                col.sched.unsuspend_cards([cid])
            col.set_deck([cid],vd); filled+=1
        for w in new:
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
        if new_nids:
            rev=col.db.list("SELECT id FROM cards WHERE nid IN (%s) AND ord=1"%",".join(map(str,new_nids)))
            col.sched.suspend_cards(rev)
        # reposition
        newcards=col.db.all("SELECT c.id,c.nid FROM cards c WHERE c.did=? AND c.type=0 AND c.ord=0",vd)
        order=[]
        for cid,nid in newcards:
            flds=col.db.scalar("SELECT flds FROM notes WHERE id=?",nid)
            ww=re.sub(r"<[^>]+>","",flds.split(SEP)[0]).strip()
            order.append((zipf_frequency(ww,"zh") if ww else 0.0,cid))
        order.sort(key=lambda x:-x[0])
        col.sched.reposition_new_cards([c for _,c in order],starting_from=1,step_size=1,randomize=False,shift_existing=False)
        tot=col.db.scalar("SELECT COUNT(*) FROM cards WHERE did=? AND type=0 AND ord=0",vd)
        print(f"APPLIED: filled {filled} existing, created {created} new. Vocab forward new-card queue: {tot}")
    else:
        print("DRY-RUN (no changes).")
finally:
    col.close()
