#!/usr/bin/env python3
"""Create or update grammar-pattern prompts directly in Reverse::2 General.

Input is a [{key, front, back}] JSON list; the existing script now targets Reverse.
Dry run by default; live writes must run through freq_data/anki_op.sh.
"""

import argparse
import json
import re
import sys

from anki.collection import Collection

ROOT = "/home/vincent/anki-headless"
sys.path.insert(0, ROOT)
import decks  # noqa: E402
from bot import set_new_card_position  # noqa: E402
from set_new_per_day import sync  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--db", default=f"{ROOT}/collection.anki2")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--no-sync", action="store_true")
    args = parser.parse_args()

    specs = json.load(open(args.data, encoding="utf-8"))
    keys = [spec["key"] for spec in specs]
    if not specs or len(keys) != len(set(keys)):
        raise SystemExit("Pattern keys must be nonempty and unique")
    for spec in specs:
        if not re.fullmatch(r"[a-z0-9-]+", spec["key"]):
            raise SystemExit(f"Invalid pattern key: {spec['key']!r}")
        if not spec["front"].strip() or not spec["back"].strip():
            raise SystemExit(f"Empty pattern card: {spec['key']}")
        if "{{c" in spec["front"]:
            raise SystemExit(f"Raw Cloze template in Reverse prompt: {spec['key']}")
        answer = re.sub(r"<[^>]+>", "", spec["back"]).split("。", 1)[0]
        if answer and answer in re.sub(r"<[^>]+>", "", spec["front"]):
            raise SystemExit(f"Front reveals the answer sentence: {spec['key']}")

    col = Collection(args.db)
    try:
        model = col.models.by_name("Basic")
        target = col.decks.id_for_name(decks.PRODUCTION_GENERAL_DECK)
        if model is None or target is None or col.decks.get(target)["dyn"]:
            raise RuntimeError("Basic model or Reverse General deck missing")
        if col.decks.id_for_name("Patterns") is not None:
            raise RuntimeError("retired Patterns deck was recreated; inspect before writing")

        existing = {}
        for nid in col.find_notes("tag:practice::grammar-pattern"):
            note = col.get_note(nid)
            if note.note_type()["id"] != model["id"]:
                continue
            for tag in note.tags:
                if tag.startswith("pattern::"):
                    if tag in existing:
                        raise RuntimeError(f"duplicate tag {tag}: {existing[tag]}, {nid}")
                    existing[tag] = nid

        for spec in specs:
            tag = f"pattern::{spec['key']}"
            nid = existing.get(tag)
            if nid is None:
                print(f"CREATE {tag} in {decks.PRODUCTION_GENERAL_DECK}")
            else:
                note = col.get_note(nid)
                card = note.cards()[0]
                if card.did != target:
                    raise RuntimeError(f"{tag}: existing card is outside Reverse General")
                print(f"UPDATE {tag} (note {nid}; queue={card.queue})")
        if not args.apply:
            print("DRY RUN: nothing changed")
            return

        new_cids = []
        for spec in specs:
            tag = f"pattern::{spec['key']}"
            nid = existing.get(tag)
            if nid is None:
                note = col.new_note(model)
                note["Front"] = spec["front"]
                note["Back"] = spec["back"]
                note.add_tag("practice::grammar-pattern")
                note.add_tag(tag)
                col.add_note(note, target)
                new_cids.append(note.cards()[0].id)
            else:
                note = col.get_note(nid)
                if note["Front"] != spec["front"] or note["Back"] != spec["back"]:
                    note["Front"] = spec["front"]
                    note["Back"] = spec["back"]
                    col.update_note(note)
        if new_cids:
            others = ",".join("?" * len(new_cids))
            first = col.db.scalar(
                f"select min(due) from cards where did=? and queue=0 and type=0 "
                f"and id not in ({others})", target, *new_cids)
            pos = (first if first is not None else 1) - len(new_cids)
            for cid in new_cids:
                card = col.get_card(cid)
                if card.queue != 0 or card.type != 0 or card.did != target:
                    raise RuntimeError(f"new card {cid} has unexpected state")
                set_new_card_position(col, card, pos)
                pos += 1
        for spec in specs:
            tag = f"pattern::{spec['key']}"
            nids = col.find_notes(f"tag:{tag}")
            if len(nids) != 1:
                raise RuntimeError(f"{tag}: expected one note, got {nids}")
            note = col.get_note(nids[0])
            card = note.cards()[0]
            if note["Front"] != spec["front"] or note["Back"] != spec["back"] or card.did != target:
                raise RuntimeError(f"{tag}: verification failed")
            print(f"VERIFIED {tag}: card {card.id} in Reverse General, queue={card.queue}")
        if not args.no_sync:
            sync(col)  # media disabled
    finally:
        col.close()


if __name__ == "__main__":
    main()
