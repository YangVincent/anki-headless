import re,sys
from anki.collection import Collection
APPLY="--apply" in sys.argv
def clean(s): return re.sub(r'<[^>]+>','',s or '').strip()
col=Collection("/home/vincent/anki-headless/collection.anki2")
try:
    cv=next(m for m in col.models.all() if m["name"]=="ChineseVocabulary")
    fi={f["name"]:i for i,f in enumerate(cv["flds"])}; SEP=chr(31)
    print("template renders {{Notes}}:", "Notes" in cv["tmpls"][0]["afmt"])
    vd=col.decks.id_for_name("Vocab")
    nid=col.db.scalar("SELECT n.id FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND n.mid=? AND n.flds LIKE ?",vd,cv["id"],"具有"+SEP+"%")
    note=col.get_note(nid)
    html=("<b>具有 vs 有</b><br>"
          "• <b>有</b> = everyday “have” — works with anything: 有钱, 有书, 有问题.<br>"
          "• <b>具有</b> = formal/written “to possess” — only <b>abstract qualities</b>: "
          "具有意义 / 特点 / 影响力 / 能力 / 代表性. ✗ 具有一本书 (can’t possess a physical thing).<br>"
          "具有 can drop down to 有 (just less formal); 有 can’t rise to 具有 for concrete things.<br>"
          "Negation is 没有 — never ✗没具有.")
    note.fields[fi["Notes"]]=html
    print("Notes set to:\n  ", clean(html))
    if APPLY: col.update_note(note); print("APPLIED")
    else: print("DRY-RUN")
finally:
    col.close()
