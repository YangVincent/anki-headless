#!/usr/bin/env python3
"""Fix the 3 displayed-field defects found by the consistency audit:
太空 (pinyin mismatch), 一说 (typo), 别号 (truncated). Recompute pinyin from the
corrected sentence with pypinyin. Dry-run unless --apply. Run via anki_op.sh."""
import re, sys
from anki.collection import Collection
from pypinyin import pinyin, Style
APPLY="--apply" in sys.argv
def clean(s): return re.sub(r'<[^>]+>','',s or '').replace('\xa0',' ').strip()
def mkpy(s):
    toks=pinyin(s, style=Style.TONE)
    out=' '.join(t[0] for t in toks)
    return out[:1].upper()+out[1:]
def bold(s,w): return s.replace(w,f"<b>{w}</b>",1) if w in s else s
def cloze(s,w): return s.replace(w,"[ ]",1) if w in s else s

# (word, substring to locate the defective card, corrected simplified sentence, corrected pinyin)
FIXES=[
 ("太空","太空船顺利返回地球","太空船顺利返回地球。",
   "Tàikōngchuán shùnlì fǎnhuí dìqiú."),
 ("一说","另一一说","关于这件事的起因，民间还有另一说。",
   "Guānyú zhè jiàn shì de qǐyīn, mínjiān hái yǒu lìng yī shuō."),
 ("别号","他的别号是","他的别号是“老顽童”，朋友都这么叫他。",
   "Tā de biéhào shì “lǎo wántóng”, péngyǒu dōu zhème jiào tā."),
]
col=Collection("/home/vincent/anki-headless/collection.anki2")
try:
    cv=next(m for m in col.models.all() if m['name']=='ChineseVocabulary')
    fi={f['name']:i for i,f in enumerate(cv['flds'])}; SEP=chr(31)
    vd=col.decks.id_for_name("Vocab")
    # nid lookup by scanning cleaned text (sentence field is bolded HTML)
    allrows=col.db.all("SELECT n.id,n.flds FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND n.mid=?", vd, cv['id'])
    def find(word,locate):
        for nid,flds in allrows:
            f=flds.split(SEP)
            if clean(f[fi['Simplified']])==word and locate in clean(f[fi['SentenceSimplified']]):
                return nid
        return None
    for word,locate,newsent,newpy in FIXES:
        nid=find(word,locate)
        if not nid:
            print(f"  {word}: NOT FOUND (locate={locate!r})"); continue
        note=col.get_note(nid)
        old=clean(note.fields[fi['SentenceSimplified']])
        print(f"  {word}: old='{old}' -> new='{newsent}'  pinyin='{newpy}'")
        if APPLY:
            note.fields[fi['SentenceSimplified']]=bold(newsent,word)
            note.fields[fi['SentenceSimplifiedCloze']]=cloze(newsent,word)
            note.fields[fi['SentencePinyin']]=newpy
            col.update_note(note)
    print("APPLIED" if APPLY else "DRY-RUN")
finally:
    col.close()
