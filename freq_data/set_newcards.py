#!/usr/bin/env python3
"""Set Vocab deck new-cards/day limit. Verifies before exit. Run via anki_op.sh."""
import sys
from anki.collection import Collection

NEW_PER_DAY = int(sys.argv[1]) if len(sys.argv) > 1 else 20
col = Collection("/home/vincent/anki-headless/collection.anki2")
vd = col.decks.id_for_name("Vocab")
deck = col.decks.get(vd)
conf = col.decks.config_dict_for_deck_id(vd)
print(f"deck 'Vocab' uses options preset: {conf['name']!r} (id={conf['id']})")
print(f"  current new/day = {conf['new']['perDay']} | review/day = {conf['rev']['perDay']}")
old = conf['new']['perDay']
conf['new']['perDay'] = NEW_PER_DAY
col.decks.update_config(conf)
# verify
conf2 = col.decks.config_dict_for_deck_id(vd)
print(f"  new/day: {old} -> {conf2['new']['perDay']}")
assert conf2['new']['perDay'] == NEW_PER_DAY
col.close()
print("done")
