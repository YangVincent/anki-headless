#!/usr/bin/env python3
"""Apply QA corrections to flagged cards (by nid). Robust loader (salvages
malformed/corrupt batch files). Re-validates the corrected word-in-sentence,
re-derives bold + cloze, recomputes pinyin from the sentence ONLY if the agent's
pinyin doesn't transcribe it. Dry-run unless --apply. Run via anki_op.sh."""
import json, glob, re, sys, unicodedata, difflib
from anki.collection import Collection
from pypinyin import pinyin as pyin, Style

ROOT="/home/vincent/anki-headless"
APPLY="--apply" in sys.argv
def clean(s): return re.sub(r'<[^>]+>','',s or '').replace('\xa0',' ').strip()
def bold(s,w): return s.replace(w,f"<b>{w}</b>",1) if w in s else s
def cloze(s,w): return s.replace(w,"[ ]",1) if w in s else s
def baseletters(s): return ''.join(c for c in unicodedata.normalize('NFD',s.lower()) if 'a'<=c<='z')
def pinyin_ok(sent,py):
    if re.search(r'[0-9A-Za-z]',sent): return True  # skip number/latin sentences
    exp=baseletters(''.join(x[0] for x in pyin(re.sub(r'[^一-鿿]','',sent),style=Style.NORMAL)))
    got=baseletters(py)
    return (not exp) or (not got) or difflib.SequenceMatcher(None,exp,got).ratio()>=0.82

def load_any(f):
    try: return json.load(open(f,encoding="utf-8"))
    except Exception:
        raw=open(f,encoding="utf-8",errors="replace").read()
        out=[]
        for m in re.finditer(r'\{[^{}]*?"nid":\s*(\d+)[^{}]*?"word":\s*"(.*?)"[^{}]*?"sent_simp":\s*"(.*?)"[^{}]*?"sent_trad":\s*"(.*?)"[^{}]*?"pinyin":\s*"(.*?)"[^{}]*?"english":\s*"(.*?)"[^{}]*?\}', raw, re.S):
            out.append(dict(nid=int(m.group(1)),word=m.group(2),sent_simp=m.group(3),sent_trad=m.group(4),pinyin=m.group(5),english=m.group(6)))
        return out

corr={}
for f in glob.glob(f"{ROOT}/freq_data/qa/out_*.json"):
    for e in load_any(f):
        if e.get("nid") and e.get("sent_simp") and "�" not in (e.get("sent_simp","")+e.get("pinyin","")+e.get("english","")):
            corr[int(e["nid"])]=e
print(f"corrections proposed: {len(corr)}")

col=Collection(f"{ROOT}/collection.anki2")
try:
    cv=next(m for m in col.models.all() if m["name"]=="ChineseVocabulary")
    fi={f["name"]:i for i,f in enumerate(cv["flds"])}
    applied=skipped=pyfix=0
    for nid,e in corr.items():
        w=clean(e["word"]); s=clean(e["sent_simp"])
        if not s or w not in s: skipped+=1; continue
        try: note=col.get_note(nid)
        except Exception: skipped+=1; continue
        if clean(note.fields[fi["Simplified"]])!=w: skipped+=1; continue  # nid/word sanity
        tw=clean(note.fields[fi["Traditional"]]) or w
        py=e.get("pinyin","")
        if not pinyin_ok(s,py):
            py=' '.join(x[0] for x in pyin(s,style=Style.TONE)); pyfix+=1
            py=py[:1].upper()+py[1:]
        note.fields[fi["SentenceSimplified"]]=bold(s,w)
        note.fields[fi["SentenceTraditional"]]=bold(clean(e.get("sent_trad","")),tw)
        note.fields[fi["SentenceSimplifiedCloze"]]=cloze(s,w)
        note.fields[fi["SentenceTraditionalCloze"]]=cloze(clean(e.get("sent_trad","")),tw)
        note.fields[fi["SentencePinyin"]]=py
        note.fields[fi["SentenceMeaning"]]=clean(e.get("english",""))
        if APPLY: col.update_note(note)
        applied+=1
    print(f"{'APPLIED' if APPLY else 'DRY-RUN'}: corrected {applied}, skipped {skipped}, pinyin recomputed {pyfix}")
finally:
    col.close()
