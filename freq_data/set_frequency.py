#!/usr/bin/env python3
"""Populate CustomFreq (tier + zipf + stars) on every Vocab ChineseVocabulary
note, and add a frequency line to the card back template. Idempotent — safe to
re-run after new cards are added. Dry-run unless --apply. Run via anki_op.sh.
NOTE: the template edit bumps the notetype schema -> next sync is a full upload."""
import re, sys
from anki.collection import Collection
from wordfreq import zipf_frequency

ROOT="/home/vincent/anki-headless"
APPLY="--apply" in sys.argv

def badge(word):
    z = zipf_frequency(word, "zh")
    if z >= 5:    tier, stars = "very common", 5
    elif z >= 4:  tier, stars = "common", 4
    elif z >= 3.5: tier, stars = "mid", 3
    elif z >= 3:  tier, stars = "uncommon", 2
    elif z > 0:   tier, stars = "rare", 1
    else:         return "rare · zipf 0"
    return f"{'★'*stars} {tier} · zipf {z:.1f}"

FREQ_TMPL = ('{{#CustomFreq}}<div class="freqbadge" '
             'style="font-size:11px;color:#9aa;margin-top:6px">{{CustomFreq}}</div>'
             '{{/CustomFreq}}')

col=Collection(f"{ROOT}/collection.anki2")
try:
    SEP=chr(31)
    cv=next(m for m in col.models.all() if m["name"]=="ChineseVocabulary")
    fi={f["name"]:i for i,f in enumerate(cv["flds"])}
    vd=col.decks.id_for_name("Vocab")
    nids=col.db.list("SELECT DISTINCT n.id FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND n.mid=?", vd, cv["id"])
    print(f"Vocab ChineseVocabulary notes: {len(nids)}")
    tmpl_has = FREQ_TMPL.split('"')[0] in cv["tmpls"][0]["afmt"] or "freqbadge" in cv["tmpls"][0]["afmt"]
    print(f"template already shows frequency: {tmpl_has}")
    if APPLY:
        updated=0
        for nid in nids:
            note=col.get_note(nid)
            w=re.sub(r"<[^>]+>","",note.fields[fi["Simplified"]]).strip()
            if not w: continue
            val=badge(w)
            if note.fields[fi["CustomFreq"]] != val:
                note.fields[fi["CustomFreq"]]=val
                col.update_note(note); updated+=1
        print(f"populated CustomFreq on {updated} notes")
        if not tmpl_has:
            # insert the frequency line right after the Meaning block on the back
            t=cv["tmpls"][0]
            anchor='<div class=wordtype>{{Meaning}}</div>'
            if anchor in t["afmt"]:
                t["afmt"]=t["afmt"].replace(anchor, anchor+"\n"+FREQ_TMPL, 1)
            else:
                t["afmt"]=t["afmt"]+"\n"+FREQ_TMPL
            col.models.update_dict(cv)
            print("added frequency line to card back template (schema changed -> full sync needed)")
        else:
            print("template unchanged")
    else:
        print("DRY-RUN. sample badges:", [badge(w) for w in ["的","朋友","央行","残酷","犄角"]])
finally:
    col.close()
