#!/usr/bin/env python3
"""Apply ONLY the proposed changes that the one-card-per-agent verifier marked
'use_new'. Pulls the new sentence from changed.json by nid. Full safety: nid's
actual word must match, word must appear in the new sentence, pinyin recomputed
if it doesn't transcribe the sentence. Dry-run unless --apply. Run via anki_op.sh."""
import json, glob, re, sys, unicodedata, difflib
from anki.collection import Collection
from pypinyin import pinyin as pyin, Style
ROOT="/home/vincent/anki-headless"
APPLY="--apply" in sys.argv
def clean(s): return re.sub(r'<[^>]+>','',s or '').replace('\xa0',' ').strip()
def bold(s,w): return s.replace(w,f"<b>{w}</b>",1) if w in s else s
def cloze(s,w): return s.replace(w,"[ ]",1) if w in s else s
def bl(s): return ''.join(c for c in unicodedata.normalize('NFD',s.lower()) if 'a'<=c<='z')
def pinyin_ok(sent,py):
    if re.search(r'[0-9A-Za-z]',sent): return True
    exp=bl(''.join(x[0] for x in pyin(re.sub(r'[^一-鿿]','',sent),style=Style.NORMAL))); got=bl(py)
    return (not exp) or (not got) or difflib.SequenceMatcher(None,exp,got).ratio()>=0.82

changed={c['nid']:c for c in json.load(open(f"{ROOT}/freq_data/qa/changed.json"))}
verdict={}
for f in glob.glob(f"{ROOT}/freq_data/cmp/verdict_*.json"):
    try:
        v=json.load(open(f)); verdict[int(v['nid'])]=v.get('verdict')
    except Exception: pass
use_new=[nid for nid,vd in verdict.items() if vd=='use_new']
print(f"verdicts loaded: {len(verdict)} | use_new: {len(use_new)} | keep_old: {sum(1 for v in verdict.values() if v=='keep_old')}")

col=Collection(f"{ROOT}/collection.anki2")
try:
    cv=next(m for m in col.models.all() if m["name"]=="ChineseVocabulary")
    fi={f["name"]:i for i,f in enumerate(cv["flds"])}
    applied=skipped=pyfix=0
    for nid in use_new:
        c=changed.get(nid)
        if not c: skipped+=1; continue
        w=clean(c['word']); s=clean(c['new'])
        if not s or w not in s: skipped+=1; continue
        try: note=col.get_note(nid)
        except Exception: skipped+=1; continue
        if clean(note.fields[fi['Simplified']])!=w: skipped+=1; continue
        tw=clean(note.fields[fi['Traditional']]) or w
        py=c.get('new_py','')
        if not pinyin_ok(s,py):
            py=' '.join(x[0] for x in pyin(s,style=Style.TONE)); py=py[:1].upper()+py[1:]; pyfix+=1
        note.fields[fi['SentenceSimplified']]=bold(s,w)
        note.fields[fi['SentenceTraditional']]=bold(clean(c.get('new_trad','')),tw)
        note.fields[fi['SentenceSimplifiedCloze']]=cloze(s,w)
        note.fields[fi['SentenceTraditionalCloze']]=cloze(clean(c.get('new_trad','')),tw)
        note.fields[fi['SentencePinyin']]=py
        note.fields[fi['SentenceMeaning']]=clean(c.get('new_eng',''))
        if APPLY: col.update_note(note)
        applied+=1
    print(f"{'APPLIED' if APPLY else 'DRY-RUN'}: applied {applied}, skipped {skipped}, pinyin recomputed {pyfix}")
finally:
    col.close()
