#!/usr/bin/env python3
"""Replace the (anime-subtitle) sentences on the regenerated Vocab cards with the
fresh ones. Robust loader (salvages malformed/corrupt files). Validates the word
appears in the new sentence; derives bold + cloze. Recomputes pinyin from the
sentence if the agent's pinyin doesn't match. Dry-run unless --apply. Run via anki_op.sh."""
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
def load_any(f):
    try: return json.load(open(f,encoding="utf-8"))
    except Exception:
        raw=open(f,encoding="utf-8",errors="replace").read(); out=[]
        for m in re.finditer(r'\{[^{}]*?"word":\s*"(.*?)"[^{}]*?"sent_simp":\s*"(.*?)"[^{}]*?"sent_trad":\s*"(.*?)"[^{}]*?"pinyin":\s*"(.*?)"[^{}]*?"english":\s*"(.*?)"[^{}]*?\}', raw, re.S):
            out.append(dict(word=m.group(1),sent_simp=m.group(2),sent_trad=m.group(3),pinyin=m.group(4),english=m.group(5)))
        return out

sent={}
for f in glob.glob(f"{ROOT}/freq_data/regen/out_*.json"):
    for e in load_any(f):
        w=e.get("word")
        if w and e.get("sent_simp") and "�" not in (e["sent_simp"]+e.get("pinyin","")+e.get("english","")):
            sent[w]=e
print(f"generated sentences loaded: {len(sent)}")

col=Collection(f"{ROOT}/collection.anki2")
try:
    cv=next(m for m in col.models.all() if m["name"]=="ChineseVocabulary")
    fi={f["name"]:i for i,f in enumerate(cv["flds"])}; SEP=chr(31)
    vd=col.decks.id_for_name("Vocab")
    # only the cards we targeted: had a sentence but no SentenceMeaning
    rows=col.db.all("SELECT n.id,n.flds FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND c.ord=0 AND n.mid=?", vd, cv["id"])
    applied=skipped=pyfix=0
    for nid,flds in rows:
        f=flds.split(SEP); w=clean(f[fi["Simplified"]])
        if clean(f[fi["SentenceMeaning"]]): continue   # already has English -> not a regen target
        e=sent.get(w)
        if not e: continue
        s=clean(e["sent_simp"])
        if not s or w not in s: skipped+=1; continue
        note=col.get_note(nid)
        tw=clean(note.fields[fi["Traditional"]]) or w
        py=e.get("pinyin","")
        if not pinyin_ok(s,py):
            py=' '.join(x[0] for x in pyin(s,style=Style.TONE)); py=py[:1].upper()+py[1:]; pyfix+=1
        note.fields[fi["SentenceSimplified"]]=bold(s,w)
        note.fields[fi["SentenceTraditional"]]=bold(clean(e.get("sent_trad","")),tw)
        note.fields[fi["SentenceSimplifiedCloze"]]=cloze(s,w)
        note.fields[fi["SentenceTraditionalCloze"]]=cloze(clean(e.get("sent_trad","")),tw)
        note.fields[fi["SentencePinyin"]]=py
        note.fields[fi["SentenceMeaning"]]=clean(e.get("english",""))
        if APPLY: col.update_note(note)
        applied+=1
    print(f"{'APPLIED' if APPLY else 'DRY-RUN'}: replaced {applied} sentences, skipped {skipped} (word-not-in-sent), pinyin recomputed {pyfix}")
finally:
    col.close()
