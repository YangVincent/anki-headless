#!/usr/bin/env python3
"""Patch and group a vocabulary distinction, then sync once without media.

Run through the collection-operation wrapper:

  bash freq_data/anki_op.sh disambiguation-upsert \
    freq_data/disambiguation_upsert.py spec.json

Spec shape:

  {
    "group": {
      "id": "jinbu-gaijin",
      "category": "progress-action",
      "rule": "Something progresses; someone improves a specific thing.",
      "members": [
        {"word": "进步", "cue": "...", "pattern": "X 进步了"},
        {"word": "改进", "cue": "...", "pattern": "改进 + thing"}
      ]
    },
    "fields": {
      "进步": {"Meaning": "...", "Notes": "..."},
      "改进": {"Meaning": "...", "Notes": "..."}
    }
  }

Every member must resolve to exactly one live ChineseVocabulary note. The command tags
each note `disambiguation::<group-id>`, applies optional fields, atomically updates the
dashboard registry, and syncs the collection with media disabled.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = "/home/vincent/anki-headless"
COLLECTION = f"{ROOT}/collection.anki2"
AUTH_FILE = os.path.expanduser("~/.anki_auth")

sys.path.insert(0, ROOT)
import anki_sync
import decks
import disambiguations
from anki.collection import Collection


def load_auth():
    if not os.path.exists(AUTH_FILE):
        return None
    from anki.sync import SyncAuth

    data = json.loads(Path(AUTH_FILE).read_text())
    auth = SyncAuth()
    auth.hkey = data["hkey"]
    if data.get("endpoint"):
        auth.endpoint = data["endpoint"]
    return auth, data


def live_note_for_word(col, model_id, archived, word):
    matches = []
    for nid in col.db.list("SELECT id FROM notes WHERE mid=? AND sfld=?", model_id, word):
        cards = col.get_note(nid).cards()
        if any((card.odid or card.did) not in archived for card in cards):
            matches.append(nid)
    if len(matches) != 1:
        raise RuntimeError(f"expected one live ChineseVocabulary note for {word!r}, found {matches}")
    return col.get_note(matches[0])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec")
    parser.add_argument("--registry", default=str(disambiguations.REGISTRY_PATH))
    parser.add_argument("--no-sync", action="store_true")
    args = parser.parse_args()

    spec = json.loads(Path(args.spec).read_text())
    group = spec.get("group")
    fields = spec.get("fields", {})
    if not isinstance(group, dict):
        raise SystemExit("spec must contain a group object")
    if not isinstance(fields, dict):
        raise SystemExit("fields must be an object keyed by word")

    registry = disambiguations.load_registry(args.registry)
    candidate = {**registry, "groups": [
        group if existing["id"] == group.get("id") else existing
        for existing in registry["groups"]
    ]}
    if not any(existing["id"] == group.get("id") for existing in registry["groups"]):
        candidate["groups"].append(group)
    disambiguations.validate_registry(candidate)

    col = Collection(COLLECTION)
    try:
        model = col.models.by_name("ChineseVocabulary")
        if not model:
            raise RuntimeError("ChineseVocabulary note type is missing")
        archived = decks.archive_ids(col)

        notes = {}
        for member in group["members"]:
            word = member["word"]
            note = live_note_for_word(col, model["id"], archived, word)
            requested = fields.get(word, {})
            if not isinstance(requested, dict):
                raise RuntimeError(f"fields for {word!r} must be an object")
            missing = [name for name in requested if name not in note]
            if missing:
                raise RuntimeError(f"fields not in ChineseVocabulary for {word!r}: {missing}")
            notes[word] = (note, requested)
        unknown = set(fields) - set(notes)
        if unknown:
            raise RuntimeError(f"fields supplied for words outside the group: {sorted(unknown)}")

        changed = []
        tag = f"disambiguation::{group['id']}"
        for word, (note, requested) in notes.items():
            changed_fields = []
            for name, value in requested.items():
                if note[name] != value:
                    note[name] = value
                    changed_fields.append(name)
            had_tag = note.has_tag(tag)
            if not had_tag:
                note.add_tag(tag)
            if changed_fields or not had_tag:
                col.update_note(note)
            changed.append({"word": word, "note_id": note.id,
                            "fields": changed_fields, "tag_added": not had_tag})

        disambiguations.upsert_group(group, args.registry)
        print(json.dumps({"group": group["id"], "members": changed},
                         ensure_ascii=False, indent=2))

        if args.no_sync:
            return 0
        loaded = load_auth()
        if loaded is None:
            print("WARNING: ~/.anki_auth missing; changes are local only.")
            return 0
        auth, data = loaded
        endpoint_before = auth.endpoint
        report = anki_sync.sync(col, auth, media=False)
        if auth.endpoint != endpoint_before:
            data["endpoint"] = auth.endpoint
            Path(AUTH_FILE).write_text(json.dumps(data))
            os.chmod(AUTH_FILE, 0o600)
        print("sync: " + report)
        return 0 if getattr(report, "ok", True) else 1
    finally:
        col.close()


if __name__ == "__main__":
    raise SystemExit(main())
