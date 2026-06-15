#!/usr/bin/env python3
"""Fix the 6 semantic-audit failures. Per card: locate by word+substring, then
update sentence/pinyin/english/cloze (None = keep existing). Run via anki_op.sh."""
import re, sys
from anki.collection import Collection
APPLY="--apply" in sys.argv
def clean(s): return re.sub(r'<[^>]+>','',s or '').replace('\xa0',' ').strip()
def bold(s,w): return s.replace(w,f"<b>{w}</b>",1) if w in s else s
def cloze(s,w): return s.replace(w,"[ ]",1) if w in s else s

# word, locate-substring, new_simp|None, new_pinyin|None, new_english|None
FIXES=[
 ("别号","别号是", None, None,
   "His alias is “Old Naughty Kid”, and his friends all call him that."),
 ("马刺","石板路", None, None,
   "The spurs on the knight's boots made a crisp sound on the flagstone road."),
 ("公积金","公积金贷款", None, None,
   "When buying a home, you can take out a loan using your provident fund."),
 ("约法","约法三章","民国初年颁布了《临时约法》。",
   "Línguó chūnián bānbùle 《Línshí Yuēfǎ》.",
   "In the early years of the Republic, the Provisional Constitution (临时约法) was promulgated."),
 ("女优","女优","“女优”这个词如今多指成人电影演员。",
   "“Nǚyōu” zhège cí rújīn duō zhǐ chéngrén diànyǐng yǎnyuán.",
   "The term 女优 nowadays mostly refers to adult-film actresses."),
 ("聚居","聚居","许多少数民族聚居在这个地区。",
   "Xǔduō shǎoshù mínzú jùjū zài zhège dìqū.",
   "Many ethnic minority groups live together in this region."),
]
col=Collection("/home/vincent/anki-headless/collection.anki2")
try:
    cv=next(m for m in col.models.all() if m['name']=='ChineseVocabulary')
    fi={f['name']:i for i,f in enumerate(cv['flds'])}; SEP=chr(31)
    vd=col.decks.id_for_name("Vocab")
    allrows=col.db.all("SELECT n.id,n.flds FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND n.mid=?", vd, cv['id'])
    for word,locate,simp,py,eng in FIXES:
        nid=next((nid for nid,flds in allrows
                  if clean(flds.split(SEP)[fi['Simplified']])==word and locate in clean(flds.split(SEP)[fi['SentenceSimplified']])), None)
        if not nid: print(f"  {word}: NOT FOUND"); continue
        note=col.get_note(nid)
        if simp is not None:
            note.fields[fi['SentenceSimplified']]=bold(simp,word)
            note.fields[fi['SentenceSimplifiedCloze']]=cloze(simp,word)
        if py is not None: note.fields[fi['SentencePinyin']]=py
        if eng is not None: note.fields[fi['SentenceMeaning']]=eng
        print(f"  {word}: sent={'updated' if simp else 'kept'} eng={'updated' if eng else 'kept'}")
        if APPLY: col.update_note(note)
    print("APPLIED" if APPLY else "DRY-RUN")
finally:
    col.close()
