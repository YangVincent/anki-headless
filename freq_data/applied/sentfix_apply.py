#!/usr/bin/env python3
"""Fill example sentences into Vocab cards that lacked one. Robust loader
(salvages malformed batch files, drops corrupt entries), merges hand-written
overrides, re-validates word-in-sentence, backfills empty Meaning from CEDICT.
Dry-run unless --apply. Run via anki_op.sh."""
import json, glob, re, sys
from anki.collection import Collection

ROOT="/home/vincent/anki-headless"
APPLY="--apply" in sys.argv
def clean(s): return re.sub(r'<[^>]+>','',s or '').replace('\xa0',' ').strip()

def target(word, s):
    """largest prefix of word that appears in s (handles 一边一边 -> 一边)."""
    if word in s: return word
    for k in range(len(word), 1, -1):
        if word[:k] in s: return word[:k]
    return word
def bold(s,w):
    t=target(w,s); return s.replace(t,f"<b>{t}</b>",1) if t in s else s
def cloze(s,w):
    t=target(w,s); return s.replace(t,"[ ]",1) if t in s else s

def load_any(f):
    try: return json.load(open(f,encoding="utf-8"))
    except Exception:
        raw=open(f,encoding="utf-8",errors="replace").read()
        out=[]
        for m in re.finditer(r'\{[^{}]*?"word":\s*"(.*?)"[^{}]*?"sent_simp":\s*"(.*?)"[^{}]*?"sent_trad":\s*"(.*?)"[^{}]*?"pinyin":\s*"(.*?)"[^{}]*?"english":\s*"(.*?)"[^{}]*?\}', raw, re.S):
            out.append(dict(word=m.group(1),sent_simp=m.group(2),sent_trad=m.group(3),pinyin=m.group(4),english=m.group(5)))
        return out

ced={}
with open("/home/vincent/chinese-projects/dong-chinese/Resources/cedict_ts.u8") as f:
    for line in f:
        if line.startswith("#"): continue
        m=re.match(r"(\S+) (\S+) \[([^\]]*)\] /(.+)/",line)
        if m and m.group(2) not in ced: ced[m.group(2)]=m.group(4).replace("/","; ")

fix={d["nid"]:d for d in json.load(open(f"{ROOT}/freq_data/sentence_fix_input.json"))}
sent={}
for f in glob.glob(f"{ROOT}/freq_data/sentfix/out_*.json")+glob.glob(f"{ROOT}/freq_data/sentfix2/out_*.json"):
    for e in load_any(f):
        w=e.get("word")
        if not w: continue
        blob=e.get("sent_simp","")+e.get("sent_trad","")+e.get("pinyin","")+e.get("english","")
        if "�" in blob: continue   # drop corrupt entries
        sent[w]=e
for e in json.load(open(f"{ROOT}/freq_data/sentfix/override.json")):  # overrides win
    sent[e["word"]]=e

col=Collection(f"{ROOT}/collection.anki2")
try:
    cv=next(m for m in col.models.all() if m["name"]=="ChineseVocabulary")
    fi={f["name"]:i for i,f in enumerate(cv["flds"])}
    filled=meaning_fixed=still=0; missing=[]
    for nid,d in fix.items():
        w=d["word"]; tw=d.get("trad",w); s=sent.get(w)
        if not s or not s.get("sent_simp") or target(w, s["sent_simp"]) not in s["sent_simp"]:
            still+=1; missing.append(w); continue
        try: note=col.get_note(nid)
        except Exception: continue
        note.fields[fi["SentenceSimplified"]]=bold(s["sent_simp"],w)
        note.fields[fi["SentenceTraditional"]]=bold(s.get("sent_trad",""),tw)
        note.fields[fi["SentenceSimplifiedCloze"]]=cloze(s["sent_simp"],w)
        note.fields[fi["SentenceTraditionalCloze"]]=cloze(s.get("sent_trad",""),tw)
        note.fields[fi["SentencePinyin"]]=s.get("pinyin","")
        note.fields[fi["SentenceMeaning"]]=s.get("english","")
        if not clean(note.fields[fi["Meaning"]]):
            g=ced.get(w) or ced.get(clean(note.fields[fi["Simplified"]]))
            if g: note.fields[fi["Meaning"]]=g; meaning_fixed+=1
        if APPLY: col.update_note(note)
        filled+=1
    # backfill ANY empty Meaning across the whole Vocab deck (catches 请问 etc.)
    vd=col.decks.id_for_name("Vocab"); SEP=chr(31); m_extra=0
    for nid in col.db.list("SELECT DISTINCT n.id FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND n.mid=?", vd, cv["id"]):
        note=col.get_note(nid)
        if clean(note.fields[fi["Meaning"]]): continue
        w=clean(note.fields[fi["Simplified"]]); g=ced.get(w)
        if g:
            note.fields[fi["Meaning"]]=g
            if APPLY: col.update_note(note)
            m_extra+=1
    print(f"{'APPLIED' if APPLY else 'DRY-RUN'}: filled {filled} sentences, fixed {meaning_fixed+m_extra} meanings, still-missing {still}")
    if missing: print("  still missing:", ' '.join(missing[:30]))
finally:
    col.close()
