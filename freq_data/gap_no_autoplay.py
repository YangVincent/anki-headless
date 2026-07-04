#!/usr/bin/env python3
"""Disable audio autoplay for the 'Hanly Gap' deck options group only.
Run via anki_op.sh. Dry-run unless --apply."""
import sys, os
from anki.collection import Collection

ROOT = "/home/vincent/anki-headless"
APPLY = "--apply" in sys.argv
DB = os.environ.get("GAP_DB", f"{ROOT}/collection.anki2")

col = Collection(DB)
try:
    cfg = next((g for g in col.decks.all_config() if g["name"] == "Hanly Gap"), None)
    if not cfg:
        print("ERROR: 'Hanly Gap' options group not found"); raise SystemExit(1)
    # confirm this group is scoped to the gap deck only
    users = col.decks.decks_using_config(cfg)
    names = [col.decks.get(d.id)["name"].replace(chr(31), "::")
             for d in users.assigned] if hasattr(users, "assigned") else []
    print("decks using 'Hanly Gap' config:", names or "(checking via deck table)")
    if not names:
        names = [r[1].replace(chr(31), "::") for r in col.db.execute(
            "SELECT id,name FROM decks") if col.decks.config_dict_for_deck_id(r[0]).get("id") == cfg["id"]]
        print("  ->", names)
    print(f"current autoplay={cfg['autoplay']}")
    if APPLY:
        cfg["autoplay"] = False
        col.decks.update_config(cfg)
        check = next(g for g in col.decks.all_config() if g["name"] == "Hanly Gap")
        print(f"APPLIED: autoplay now = {check['autoplay']}")
    else:
        print("DRY-RUN: would set autoplay=False")
finally:
    col.close()
