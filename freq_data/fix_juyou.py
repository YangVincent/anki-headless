import re,sys
from anki.collection import Collection
APPLY="--apply" in sys.argv
def clean(s): return re.sub(r'<[^>]+>','',s or '').strip()
col=Collection("/home/vincent/anki-headless/collection.anki2")
try:
    cv=next(m for m in col.models.all() if m["name"]=="ChineseVocabulary")
    fi={f["name"]:i for i,f in enumerate(cv["flds"])}; SEP=chr(31)
    vd=col.decks.id_for_name("Vocab")
    nid=col.db.scalar("SELECT n.id FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND n.mid=? AND n.flds LIKE ?",vd,cv["id"],"具有"+SEP+"%")
    note=col.get_note(nid)
    note.fields[fi["SentencePinyin"]]="Bùguò zhège cūnzi yě xiāngdāng jùyǒu yìshùxìng ma."
    note.fields[fi["SentenceMeaning"]]="Still, this village is quite artistic, isn't it?"
    print("SentenceSimplified:", clean(note.fields[fi["SentenceSimplified"]]))
    print("SentencePinyin ->", note.fields[fi["SentencePinyin"]])
    print("SentenceMeaning ->", note.fields[fi["SentenceMeaning"]])
    if APPLY: col.update_note(note); print("APPLIED")
    else: print("DRY-RUN")
finally:
    col.close()
