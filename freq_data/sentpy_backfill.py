#!/usr/bin/env python3
"""Backfill SentencePinyin (deterministically, via pypinyin) on every Vocab
ChineseVocabulary card that has a sentence but a blank SentencePinyin.
Only fills blanks — never overwrites. Dry-run unless --apply. Run via anki_op.sh."""
import re, sys
import jieba
from pypinyin import pinyin as pyin, Style
from anki.collection import Collection
APPLY="--apply" in sys.argv
def clean(s): return re.sub(r'<[^>]+>','',s or '').replace('\xa0',' ').strip()
def mkpy(s):
    parts=[]
    for w in jieba.cut(s):
        if re.search(r'[一-鿿]', w):
            parts.append(''.join(t[0] for t in pyin(w, style=Style.TONE)))
        elif w.strip():
            parts.append(w)
    out=''
    for p in parts:
        if not out: out=p
        elif re.match(r'^[A-Za-z0-9一-鿿]', p): out+=' '+p
        else: out+=p
    out=out.strip()
    return out[:1].upper()+out[1:] if out else out

col=Collection("/home/vincent/anki-headless/collection.anki2")
try:
    cv=next(m for m in col.models.all() if m["name"]=="ChineseVocabulary")
    fi={f["name"]:i for i,f in enumerate(cv["flds"])}; SEP=chr(31)
    vd=col.decks.id_for_name("Vocab")
    nids=col.db.list("SELECT DISTINCT n.id FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND c.ord=0 AND n.mid=?", vd, cv["id"])
    filled=0; sample=[]
    for nid in nids:
        note=col.get_note(nid)
        sent=clean(note.fields[fi["SentenceSimplified"]])
        if not sent or clean(note.fields[fi["SentencePinyin"]]): continue
        py=mkpy(sent)
        if not py: continue
        note.fields[fi["SentencePinyin"]]=py
        if APPLY: col.update_note(note)
        filled+=1
        if len(sample)<6: sample.append((sent, py))
    print(f"{'APPLIED' if APPLY else 'DRY-RUN'}: backfilled SentencePinyin on {filled} cards")
    for s,p in sample: print(f"   {s}  ->  {p}")
finally:
    col.close()
