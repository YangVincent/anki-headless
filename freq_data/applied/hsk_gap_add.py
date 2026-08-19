#!/usr/bin/env python3
"""Add ALL multi-char HSK 4-9 words missing from active study to the Vocab deck.
 - If a ChineseVocabulary note already exists (mostly Hidden::Archive::Words): UNARCHIVE
   -> move forward (ord0) to Vocab + unsuspend, suspend reverse (ord1), route cloze to
   Vocab Cloze suspended.
 - Else: CREATE a new note from HSK data.
All get tags HSK3.0::<level> + 'hsk-gap-add' (rollback handle); CustomFreq filled if empty.
Skips words that already have an ACTIVE forward card anywhere. Dry-run unless --apply.
Frequency-ordering is a separate resort_vocab.py step afterwards."""
import json, re, sys, time
from anki.collection import Collection
from wordfreq import zipf_frequency
try:
    import opencc; _s2t=opencc.OpenCC("s2t.json"); s2t=lambda w:_s2t.convert(w)
except Exception: s2t=lambda w:w

ROOT="/home/vincent/anki-headless"; APPLY="--apply" in sys.argv
POSMAP={"名":"noun","动":"verb","形":"adjective","副":"adverb","数":"numeral","量":"measure word",
        "代":"pronoun","介":"preposition","连":"conjunction","助":"particle","叹":"interjection",
        "拟":"onomatopoeia","区":"attributive","头":"prefix","尾":"suffix","短语":"phrase"}
mappos=lambda cn:", ".join(p for p in (POSMAP.get(x.strip()) for x in re.split(r"[、,]",cn)) if p)
def badge(w):
    z=zipf_frequency(w,"zh")
    t=("very common",5) if z>=5 else ("common",4) if z>=4 else ("mid",3) if z>=3.5 else ("uncommon",2) if z>0 else ("rare",1)
    return f"{'★'*t[1]} {t[0]} · zipf {z:.1f}"
HSK={r["word"]:r for r in json.load(open(f"{ROOT}/freq_data/hsk3_vocab.json"))}

col=Collection(f"{ROOT}/collection.anki2")
cv=next(m for m in col.models.all() if m["name"]=="ChineseVocabulary")
fi={f["name"]:i for i,f in enumerate(cv["flds"])}
vd=col.decks.id_for_name("Vocab"); cloze_did=col.decks.id("Vocab Cloze")
cloze_ord=next((t["ord"] for t in cv["tmpls"] if t["name"]=="Cloze-Recall"),None)

# index CV notes by word; track active forward presence
word_notes={}
active_fwd=set()
for (nid,flds) in col.db.all("SELECT id,flds FROM notes WHERE mid=?",cv["id"]):
    w=re.sub(r"<[^>]+>","",flds.split(chr(31))[0]).strip()
    if w: word_notes.setdefault(w,[]).append(nid)
for w,nids in word_notes.items():
    for nid in nids:
        for c in col.get_note(nid).cards():
            if c.ord==0 and c.queue!=-1: active_fwd.add(w)

targets=[(w,r) for w,r in HSK.items() if len(w)>1 and r["level"] in("4","5","6","7-9") and w not in active_fwd]
print(f"target multi-char HSK4-9 words w/o active forward card: {len(targets)}")

def tag_note(note,lvl):
    for t in ("chinese","hsk-gap-add",f"HSK3.0::{lvl}"):
        if not note.has_tag(t): note.add_tag(t)
    if "CustomFreq" in fi and not note.fields[fi["CustomFreq"]].strip():
        note.fields[fi["CustomFreq"]]=badge(note.fields[fi["Simplified"]])

unarch=created=rev_susp=clz=0
for w,r in targets:
    if not APPLY: continue
    if w in word_notes:                       # UNARCHIVE existing
        nid=word_notes[w][0]
        note=col.get_note(nid)
        fwd=[c for c in note.cards() if c.ord==0]
        if not fwd: continue
        col.set_deck([c.id for c in fwd], vd); col.sched.unsuspend_cards([c.id for c in fwd])
        rev=[c.id for c in note.cards() if c.ord==1 and c.queue!=-1]
        if rev: col.sched.suspend_cards(rev); rev_susp+=len(rev)
        cl=[c.id for c in note.cards() if cloze_ord is not None and c.ord==cloze_ord]
        if cl: col.set_deck(cl,cloze_did); col.sched.suspend_cards(cl); clz+=len(cl)
        tag_note(note,r["level"]); col.update_note(note); unarch+=1
    else:                                     # CREATE new
        note=col.new_note(cv)
        note.fields[fi["Simplified"]]=w; note.fields[fi["Traditional"]]=s2t(w)
        note.fields[fi["Pinyin"]]=r["pinyin"]; note.fields[fi["Meaning"]]=r["gloss"]
        if "PartOfSpeech" in fi: note.fields[fi["PartOfSpeech"]]=mappos(r["pos"])
        if "CustomFreq" in fi: note.fields[fi["CustomFreq"]]=badge(w)
        note.tags=["chinese","hsk-gap-add",f"HSK3.0::{r['level']}"]
        col.add_note(note,vd)
        for c in note.cards():
            if c.ord==1: col.sched.suspend_cards([c.id]); rev_susp+=1
            elif cloze_ord is not None and c.ord==cloze_ord:
                col.set_deck([c.id],cloze_did); col.sched.suspend_cards([c.id]); clz+=1
        created+=1

if APPLY:
    print(f"unarchived {unarch} | created {created} | reverse suspended {rev_susp} | cloze routed {clz}")
    n=len(col.find_notes("tag:hsk-gap-add"))
    act=len(col.find_cards("deck:Vocab tag:hsk-gap-add -is:suspended"))
    print(f"VERIFY: tagged hsk-gap-add={n} | active forward in Vocab={act}")
else:
    ua=sum(1 for w,_ in targets if w in word_notes)
    print(f"DRY-RUN: would UNARCHIVE {ua}, CREATE {len(targets)-ua}")
    for w,r in targets[:8]:
        print(f"  {'unarch' if w in word_notes else 'create'}  {w} HSK{r['level']} {r['pinyin']} — {r['gloss'][:34]}")
col.close()