#!/usr/bin/env python3
"""One-off: demote 人中 to a niche queue position; ensure 具有 has pinyin.
Dry-run unless --apply. Run via anki_op.sh."""
import re, sys
from anki.collection import Collection
from pypinyin import pinyin as pyin, Style
APPLY="--apply" in sys.argv
def clean(s): return re.sub(r'<[^>]+>','',s or '').strip()
def mkpy(w):
    toks=pyin(w, style=Style.TONE)
    return ''.join(t[0] for t in toks)

col=Collection("/home/vincent/anki-headless/collection.anki2")
try:
    cv=next(m for m in col.models.all() if m["name"]=="ChineseVocabulary")
    fi={f["name"]:i for i,f in enumerate(cv["flds"])}; SEP=chr(31)
    vd=col.decks.id_for_name("Vocab")

    # 1) demote 人中 -> niche position (~zipf 3.3 zone, deep in the 16k queue)
    nid=col.db.scalar("SELECT n.id FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND n.mid=? AND n.flds LIKE ?", vd, cv["id"], "人中"+SEP+"%")
    if nid:
        cid,typ,due=col.db.first("SELECT id,type,due FROM cards WHERE nid=? AND ord=0", nid)
        print(f"人中: forward card type={typ} (0=new) current due/pos={due}")
        if typ==0 and APPLY:
            col.sched.reposition_new_cards([cid], starting_from=12000, step_size=1, randomize=False, shift_existing=False)
            print("  -> repositioned to ~12,000 (deep / niche)")
        elif typ!=0:
            print("  (already studied — repositioning N/A)")
    else:
        print("人中 not found in Vocab")

    # 2) ensure 具有 has pinyin
    nid2=col.db.scalar("SELECT n.id FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND n.mid=? AND n.flds LIKE ?", vd, cv["id"], "具有"+SEP+"%")
    if nid2:
        note=col.get_note(nid2)
        cur=clean(note.fields[fi["Pinyin"]])
        want=mkpy("具有")
        print(f"具有: current Pinyin={cur!r} -> setting {want!r}")
        if APPLY and cur!=want:
            note.fields[fi["Pinyin"]]=want
            col.update_note(note)
    else:
        print("具有 not found in Vocab (checking other notetypes...)")
        for m in col.models.all():
            names=[f["name"] for f in m["flds"]]
            pk=next((n for n in names if n.lower()=="pinyin"), None)
            if not pk: continue
            n3=col.db.scalar("SELECT id FROM notes WHERE mid=? AND flds LIKE ?", m["id"], "具有"+SEP+"%")
            if n3:
                note=col.get_note(n3); idx={f["name"]:i for i,f in enumerate(m["flds"])}
                print(f"  found 具有 in notetype {m['name']}, Pinyin={clean(note.fields[idx[pk]])!r}")
                if APPLY:
                    note.fields[idx[pk]]=mkpy("具有"); col.update_note(note)
                break
    print("APPLIED" if APPLY else "DRY-RUN")
finally:
    col.close()
