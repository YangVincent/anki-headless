#!/usr/bin/env python3
"""Change new-cards/day on the preset a deck already uses.

Deliberately narrow: it edits ONE field (`new.perDay`) of an EXISTING preset and
refuses to create a new one. Creating a preset from scratch silently ships Anki's
stock defaults (new.order=RANDOM, fsrsParams6=[], autoplay=True, ...) instead of
the trained ones — that has broken this collection before.

Verification is a full recursive diff of the preset before vs after: the only
allowed differences are `new.perDay` plus the `mod`/`usn` bookkeeping fields.

Dry-run by default; pass --apply to write. Writes push to AnkiWeb immediately
(--no-sync opts out) so a study device isn't left serving the old limit.

Usage:
  .venv/bin/python freq_data/set_new_per_day.py --deck HSK --per-day 10
  bash freq_data/anki_op.sh newlimit freq_data/set_new_per_day.py --deck HSK --per-day 10 --apply
"""
import argparse
import copy
import json
import os
import sys

from anki.collection import Collection

COL = "/home/vincent/anki-headless/collection.anki2"
BOOKKEEPING = {"mod", "usn"}  # bumped by update_config, not part of the intent


def diff(a, b, path=""):
    """Recursive diff of two JSON-ish structures -> [(path, old, new)]."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            out += diff(a.get(k, "<missing>"), b.get(k, "<missing>"), f"{path}.{k}" if path else str(k))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path, f"list[{len(a)}]", f"list[{len(b)}]"))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                out += diff(x, y, f"{path}[{i}]")
    elif a != b:
        out.append((path, a, b))
    return out


def sync(col):
    auth_file = os.path.expanduser("~/.anki_auth")
    if not os.path.exists(auth_file):
        print("SYNC SKIPPED: not logged in (~/.anki_auth missing). The new limit is on "
              "the server file ONLY — your study device won't see it until you sync.")
        return
    from anki.sync import SyncAuth
    data = json.load(open(auth_file))
    auth = SyncAuth()
    auth.hkey = data["hkey"]
    if data.get("endpoint"):
        auth.endpoint = data["endpoint"]
    res = col.sync_collection(auth, sync_media=False)
    if res.new_endpoint:
        data["endpoint"] = res.new_endpoint
        json.dump(data, open(auth_file, "w"))
        os.chmod(auth_file, 0o600)
    if res.required == 2:
        print("SYNC: *** FULL SYNC REQUIRED *** — the change was NOT uploaded. "
              "Resolve with `anki-cli sync`, THEN sync your device down.")
    else:
        print(f"SYNC: pushed to AnkiWeb (status={res.required}). "
              "Sync your study device DOWN before the next session.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", required=True, help="exact deck name, e.g. HSK")
    ap.add_argument("--per-day", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-sync", action="store_true")
    args = ap.parse_args()

    col = Collection(COL)
    try:
        deck = col.decks.by_name(args.deck)
        if deck is None:
            sys.exit(f"ERROR: no deck named {args.deck!r}")
        if deck.get("dyn"):
            sys.exit(f"ERROR: {args.deck!r} is a filtered deck (no preset)")

        conf_id = deck["conf"]
        conf = col.decks.get_config(conf_id)
        before = copy.deepcopy(conf)

        # Who else rides this preset? A shared preset means this is not a
        # deck-local change, and the caller needs to know that before applying.
        sharers = [d["name"] for d in col.decks.all()
                   if not d.get("dyn") and d.get("conf") == conf_id and d["name"] != deck["name"]]

        print(f"deck  : {deck['name']!r} (id={deck['id']})")
        print(f"preset: {conf['name']!r} (id={conf_id})")
        print(f"new/day: {before['new']['perDay']} -> {args.per_day}")
        if sharers:
            print(f"WARNING: this preset is shared with {len(sharers)} other deck(s); "
                  f"they get the same limit: {', '.join(sorted(sharers))}")
        else:
            print("preset is used by this deck only")

        if before["new"]["perDay"] == args.per_day:
            print("\nAlready at the requested value — nothing to do.")
            return

        if not args.apply:
            print("\nDRY-RUN — nothing written.")
            return

        conf["new"]["perDay"] = args.per_day
        col.decks.update_config(conf)

        # Verify by full diff of the re-read preset vs the pre-change snapshot.
        # Re-reading only the field we set would prove nothing about collateral damage.
        after = col.decks.get_config(conf_id)
        deltas = diff(before, after)
        unexpected = [d for d in deltas if d[0] != "new.perDay" and d[0] not in BOOKKEEPING]
        print("\nfull preset diff (before -> after):")
        for path, old, new in deltas:
            print(f"  {path}: {old!r} -> {new!r}")
        if unexpected:
            sys.exit(f"\nERROR: unexpected field changes: {unexpected}\n"
                     f"Collection NOT synced. Restore from the anki_op backup.")
        if after["new"]["perDay"] != args.per_day:
            sys.exit("\nERROR: new.perDay did not take.")
        # The deck must still point at the same preset (no accidental re-assignment).
        assert col.decks.by_name(args.deck)["conf"] == conf_id, "deck's preset changed!"
        print("\nVERIFIED: only new.perDay changed; deck still on the same preset.")
        print("APPLIED.")

        if not args.no_sync:
            sync(col)
    finally:
        col.close()


if __name__ == "__main__":
    main()
