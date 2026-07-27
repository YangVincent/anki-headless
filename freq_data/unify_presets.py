#!/usr/bin/env python3
"""Put every deck on the HSK preset, and silence autoplay everywhere.

Audio: HSK and Hanly Gap already had autoplay off; the other eight presets had it on,
which is where the noise on the other decks was coming from. This turns it off on every
preset, including the unused ones, so an old preset cannot resurface with sound later.

One preset: rather than maintaining six near-identical configs that had drifted apart in
22-24 fields each, every non-filtered deck is pointed at HSK — the only preset whose FSRS
parameters are fitted to actual review history (see fsrs_tune.py). The others were on
Anki's factory defaults, which describe nobody's memory in particular.

Real consequences, not just tidying:
  * non-HSK drops from 20 new cards/day to 10 (its 9,074 cards are the biggest other deck)
  * Hanly Gap goes 8/day -> 10
  * leech action becomes suspend-at-10-lapses instead of tag-at-8
  * learning steps gain the 1-hour step (1m/10m/1h), which HSK keeps deliberately

No preset is created and none is deleted — creating one is what silently resets
new.order/FSRS/autoplay to stock defaults, and deleting one would re-home its decks
somewhere unpredictable. The four dead presets left over from a CrowdAnki import
(Chinese Characters/Sentences/Vocabulary, Languages) already have no decks; they are
left in place, just muted.

  unify_presets.py                # dry run
  unify_presets.py --apply        # via freq_data/anki_op.sh
  unify_presets.py --undo --apply # restore each deck's previous preset
"""
import argparse
import json
from pathlib import Path

ROOT = Path("/home/vincent/anki-headless")
COL = ROOT / "collection.anki2"
TARGET = "HSK"
BACKUP = ROOT / "freq_data/preset_backup.json"


def _sync(col):
    from anki.sync import SyncAuth
    cred = json.loads(Path("~/.anki_auth").expanduser().read_text())
    auth = SyncAuth()
    auth.hkey = cred["hkey"]
    if cred.get("endpoint"):
        auth.endpoint = cred["endpoint"]
    out = col.sync_collection(auth, sync_media=False)
    print("sync: " + {0: "nothing further to send", 1: "changes uploaded",
                      2: "FULL SYNC REQUIRED — resolve by hand"}
          .get(out.required, f"status {out.required}"))


def main():
    from anki.collection import Collection

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo", action="store_true")
    ap.add_argument("--col", default=str(COL))
    a = ap.parse_args()
    if a.apply and a.col != str(COL):
        raise SystemExit("--apply only ever writes the real collection")

    col = Collection(a.col)
    try:
        decks = [d for d in col.decks.all_names_and_ids()
                 if not col.decks.is_filtered(d.id)]

        if a.undo:
            if not BACKUP.exists():
                raise SystemExit("no backup file — nothing to undo")
            saved = json.loads(BACKUP.read_text())
            print(f"restoring {len(saved['decks'])} deck assignments "
                  f"and autoplay on {len(saved['autoplay'])} presets")
            if not a.apply:
                print("(dry run)")
                return
            for name, conf_id in saved["decks"].items():
                did = col.decks.id_for_name(name)
                if did is None:
                    continue
                deck = col.decks.get(did)
                deck["conf"] = conf_id
                col.decks.save(deck)
            for cname, val in saved["autoplay"].items():
                cf = next((c for c in col.decks.all_config() if c["name"] == cname), None)
                if cf:
                    cf["autoplay"] = val
                    col.decks.update_config(cf)
            print("restored.")
            _sync(col)
            return

        target = next(c for c in col.decks.all_config() if c["name"] == TARGET)
        confs = col.decks.all_config()
        loud = [c["name"] for c in confs if c.get("autoplay")]
        moving = [(d.name, col.decks.config_dict_for_deck_id(d.id)["name"])
                  for d in decks
                  if col.decks.config_dict_for_deck_id(d.id)["id"] != target["id"]]

        print(f"autoplay currently ON for {len(loud)} presets: {', '.join(loud)}")
        print(f"{len(moving)} decks to move onto the {TARGET} preset:")
        for name, was in moving[:25]:
            print(f"    {name:<38} (was {was})")
        if len(moving) > 25:
            print(f"    … and {len(moving)-25} more")

        if not a.apply:
            print("\n(dry run — nothing written)")
            return

        BACKUP.write_text(json.dumps({
            "decks": {d.name: col.decks.config_dict_for_deck_id(d.id)["id"] for d in decks},
            "autoplay": {c["name"]: c.get("autoplay") for c in confs},
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"previous assignments saved to {BACKUP.name}")

        for cf in confs:
            if cf.get("autoplay"):
                cf["autoplay"] = False
                col.decks.update_config(cf)

        for d in decks:
            deck = col.decks.get(d.id)
            deck["conf"] = target["id"]
            col.decks.save(deck)

        # verify
        bad = [d.name for d in decks
               if col.decks.config_dict_for_deck_id(d.id)["name"] != TARGET]
        assert not bad, f"decks not on {TARGET}: {bad}"
        still_loud = [c["name"] for c in col.decks.all_config() if c.get("autoplay")]
        assert not still_loud, f"autoplay still on: {still_loud}"
        after = col.decks.config_dict_for_deck_id(col.decks.id_for_name(TARGET))
        assert len(after["fsrsParams6"]) == 21, "HSK params went missing"
        assert after["desiredRetention"] == 0.9, "retention changed"
        print(f"\nall {len(decks)} decks now on the {TARGET} preset, autoplay off everywhere ✓")
        print(f"  retention {after['desiredRetention']}, {len(after['fsrsParams6'])} fitted "
              f"params, {after['new']['perDay']} new/day, steps {after['new']['delays']}")
        print("undo with: unify_presets.py --undo --apply")
        _sync(col)
    finally:
        col.close()


if __name__ == "__main__":
    main()
