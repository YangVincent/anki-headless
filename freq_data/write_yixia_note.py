import re,sys
from anki.collection import Collection
APPLY="--apply" in sys.argv
col=Collection("/home/vincent/anki-headless/collection.anki2")
try:
    cv=next(m for m in col.models.all() if m["name"]=="ChineseVocabulary")
    fi={f["name"]:i for i,f in enumerate(cv["flds"])}; SEP=chr(31)
    vd=col.decks.id_for_name("Vocab")
    nid=col.db.scalar("SELECT n.id FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND n.mid=? AND n.flds LIKE ?",vd,cv["id"],"以下"+SEP+"%")
    if not nid: print("以下 not in Vocab"); sys.exit()
    note=col.get_note(nid)
    html=("<b>以下 vs 下面</b><br>"
          "• <b>以下</b> = textual / quantitative: “the following” (以下信息, 以下几点 — formal) "
          "or “under a threshold” (18岁以下, 零度以下, 平均水平以下).<br>"
          "• <b>下面</b> = physical / spatial: “underneath” (桌子下面, 树下面), "
          "“next” in speech (下面我来介绍), “subordinate” (下面的人).<br>"
          "Test: under an object → 下面. A cutoff (under 18) → 以下. “See below” in writing → either (以下 is formal).")
    note.fields[fi["Notes"]]=html
    print("以下 note set.")
    if APPLY: col.update_note(note); print("APPLIED")
    else: print("DRY-RUN")
finally:
    col.close()
