#!/usr/bin/env python3
"""Build a studyable, leverage-ordered deck of the not-in-Hanly gap characters,
each carrying a component-decomposition mnemonic. Reads freq_data/chars/gap_cards.json.

Most gap chars already exist as ChineseCharacters notes suspended in
Hidden::Archive::Characters (with sentences/audio). For those we:
  - write the mnemonic into the (blank) Notes field, preserving Radicals/sentences,
  - move their SimpRecognition (ord0) card into 'Characters::Hanly Gap',
  - unsuspend it; if it was never studied (type 0) order it by leverage (rank),
    otherwise keep its existing schedule.
  - the TradRecognition (ord1) card, if any, is left in the archive untouched.
For the handful with no existing note, a fresh note+card is created in the deck.

Run via anki_op.sh for the LIVE collection (backup + bot stopped):
    freq_data/anki_op.sh gap-apply freq_data/gap_apply.py --apply
Dry-run (no --apply) prints a summary. To dry-run against a copy without
stopping the bot, set env GAP_DB to a copied .anki2 path.
"""
import json, sys, os
from anki.collection import Collection

ROOT = "/home/vincent/anki-headless"
DECK = "Characters::Hanly Gap"
CONF_NAME = "Hanly Gap"
NEW_PER_DAY = 8
APPLY = "--apply" in sys.argv
DB = os.environ.get("GAP_DB", f"{ROOT}/collection.anki2")
SEP = chr(31)

def note_html(components, mnemonic):
    return f"<b>Components:</b> {components}<br><b>Mnemonic:</b> {mnemonic}"

cards = json.load(open(f"{ROOT}/freq_data/chars/gap_cards.json"))
col = Collection(DB)
try:
    cc = next(m for m in col.models.all() if m["name"] == "ChineseCharacters")
    fi = {f["name"]: i for i, f in enumerate(cc["flds"])}
    did = col.decks.id(DECK)

    # dedicated options group, capped new/day (reuse if it already exists)
    if APPLY:
        try:
            existing_cfg = next((g for g in col.decks.all_config()
                                 if g["name"] == CONF_NAME), None)
            cid = existing_cfg["id"] if existing_cfg \
                else col.decks.add_config_returning_id(CONF_NAME)
            conf = col.decks.get_config(cid)
            conf["new"]["perDay"] = NEW_PER_DAY
            col.decks.update_config(conf)
            deck = col.decks.get(did)
            deck["conf"] = cid
            col.decks.save(deck)
        except Exception as e:
            print(f"  (options-group setup skipped: {e} — set new/day in Anki manually)")

    moved = created = reordered = kept_sched = 0
    unsuspend = []          # ord0 card ids to unsuspend
    ord1_suspend = []       # new-note trad cards to suspend
    for c in cards:
        ch = c["char"]; rank = c["rank"]
        html = note_html(c["components"], c["mnemonic"])
        nid = col.db.scalar("SELECT id FROM notes WHERE mid=? AND flds LIKE ?",
                            cc["id"], ch + SEP + "%")
        if nid:
            moved += 1
            if APPLY:
                note = col.get_note(nid)
                note.fields[fi["Notes"]] = html        # Notes is blank; Radicals preserved
                col.update_note(note)
                cid0 = col.db.scalar("SELECT id FROM cards WHERE nid=? AND ord=0", nid)
                card = col.get_card(cid0)
                card.did = did
                if card.type == 0:                     # never studied -> leverage order
                    card.due = rank + 1; reordered += 1
                else:                                  # studied before -> keep schedule
                    kept_sched += 1
                col.update_card(card)
                unsuspend.append(cid0)
            continue
        created += 1
        if APPLY:
            note = col.new_note(cc)
            note.fields[fi["Simplified"]] = ch
            note.fields[fi["Pinyin"]] = c["pinyin"]
            note.fields[fi["Meaning"]] = c["meaning"]
            note.fields[fi["Traditional"]] = c.get("trad", ch)
            note.fields[fi["Notes"]] = html
            if "Radicals" in fi and not note.fields[fi["Radicals"]].strip():
                note.fields[fi["Radicals"]] = c["components"]
            col.add_note(note, did)
            for card in note.cards():
                card.did = did
                if card.ord == 0:
                    card.type = 0; card.queue = 0; card.due = rank + 1
                else:
                    ord1_suspend.append(card.id)
                col.update_card(card)

    if APPLY:
        if unsuspend:
            col.sched.unsuspend_cards(unsuspend)   # restores proper queue per type
        if ord1_suspend:
            col.sched.suspend_cards(ord1_suspend)

    print(f"{'APPLIED' if APPLY else 'DRY-RUN'}: {moved} moved-from-archive "
          f"({reordered} leverage-ordered, {kept_sched} kept own schedule), "
          f"{created} created -> deck '{DECK}' (new/day={NEW_PER_DAY})")

    if APPLY:
        n_active = col.db.scalar(
            "SELECT count(*) FROM cards WHERE did=? AND queue!=-1", did)
        n_total = col.db.scalar("SELECT count(*) FROM cards WHERE did=?", did)
        print(f"verify: deck '{DECK}' has {n_total} cards, {n_active} active")
        for c in cards[:3]:
            nid = col.db.scalar("SELECT id FROM notes WHERE mid=? AND flds LIKE ?",
                                cc["id"], c["char"] + SEP + "%")
            row = col.db.first(
                "SELECT did,due,queue FROM cards WHERE nid=? AND ord=0", nid)
            note = col.get_note(nid)
            print(f"  {c['char']} due={row[1]} queue={row[2]} "
                  f"Notes={note.fields[fi['Notes']][:60]}")
finally:
    col.close()
