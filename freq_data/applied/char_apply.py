#!/usr/bin/env python3
"""Apply generated character mnemonics to ChineseCharacters cards.
Reads freq_data/chars/char_cards.json. Enriches an existing card's Notes field
if one exists for the character; otherwise creates a new card in the target deck.
Run via anki_op.sh. Dry-run unless --apply. Verifies inline before exit."""
import json, sys, re
from anki.collection import Collection

ROOT="/home/vincent/anki-headless"
DECK="Characters"
APPLY="--apply" in sys.argv

def note_html(components, mnemonic):
    return f"<b>Components:</b> {components}<br><b>Mnemonic:</b> {mnemonic}"

cards=json.load(open(f"{ROOT}/freq_data/chars/char_cards.json"))
col=Collection(f"{ROOT}/collection.anki2")
try:
    # ChineseCharacters notetype
    cc=next(m for m in col.models.all() if m["name"]=="ChineseCharacters")
    fi={f["name"]:i for i,f in enumerate(cc["flds"])}
    SEP=chr(31)
    enriched=created=0
    for c in cards:
        ch=c["char"]
        notes=html=note_html(c["components"],c["mnemonic"])
        # existing ChineseCharacters note for this char?
        nid=col.db.scalar("SELECT id FROM notes WHERE mid=? AND flds LIKE ?",cc["id"],ch+SEP+"%")
        if nid:
            action="enrich existing"
            if APPLY:
                note=col.get_note(nid); note.fields[fi["Notes"]]=html; col.update_note(note)
            enriched+=1
        else:
            action="create new"
            if APPLY:
                note=col.new_note(cc)
                note.fields[fi["Simplified"]]=ch
                note.fields[fi["Pinyin"]]=c["pinyin"]
                note.fields[fi["Meaning"]]=c["meaning"]
                note.fields[fi["Traditional"]]=c.get("trad",ch)
                note.fields[fi["Notes"]]=html
                if "Radicals" in fi: note.fields[fi["Radicals"]]=c["components"]
                col.add_note(note,col.decks.id(DECK))
            created+=1
        print(f"  {ch}: {action}")
    print(f"\n{'APPLIED' if APPLY else 'DRY-RUN'}: {enriched} enriched, {created} created (deck '{DECK}')")
    if APPLY:
        # verify one
        ch=cards[0]["char"]
        nid=col.db.scalar("SELECT id FROM notes WHERE mid=? AND flds LIKE ?",cc["id"],ch+SEP+"%")
        note=col.get_note(nid)
        print(f"verify {ch} Notes field -> {note.fields[fi['Notes']][:120]}")
finally:
    col.close()
