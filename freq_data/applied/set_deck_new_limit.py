"""Set ONE deck's new-cards/day without touching the preset other decks share.

WHY A DECK-LEVEL LIMIT. Most decks here sit on the preset named 'HSK'
(id 1783563765335): Archive, Cloze, Default, HSK7-9, Mined, Reverse and non-HSK all
share it. Editing `new.perDay` there changes all seven at once. The v3 scheduler
(sched2021=True) honours a per-deck `newLimit` that overrides the preset, so the change
lands on the named deck alone.

Use freq_data/set_new_per_day.py instead when a deck owns its preset outright (HSK does).
This tool is the one for decks that share.

Verification, all of it before the write is trusted:
  * the shared preset is compared field by field, before vs after;
  * every deck's effective ceiling is snapshotted, and exactly one may change.

Run through freq_data/anki_op.sh. Dry-run by default; pass --apply to write.

  bash freq_data/anki_op.sh minednew freq_data/set_deck_new_limit.py \
       --deck Mined --per-day 3 --apply
  bash freq_data/anki_op.sh minednew freq_data/set_deck_new_limit.py \
       --deck Mined --clear --apply        # back to whatever the preset says
"""
import argparse
import sys

from anki.collection import Collection

COL = "/home/vincent/anki-headless/collection.anki2"


def snapshot(col):
    """Effective new-card ceiling for every non-dynamic deck."""
    out = {}
    for d in col.decks.all_names_and_ids():
        deck = col.decks.get(d.id)
        if not deck or deck.get("dyn"):
            continue
        cfg = col.decks.config_dict_for_deck_id(d.id)
        out[d.name] = (cfg["id"], cfg["new"]["perDay"], deck.get("newLimit"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", required=True)
    ap.add_argument("--per-day", type=int)
    ap.add_argument("--clear", action="store_true", help="remove the override")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not args.clear and args.per_day is None:
        sys.exit("give --per-day N or --clear")

    col = Collection(COL)
    try:
        did = col.decks.id_for_name(args.deck)
        if did is None:
            sys.exit(f"no deck named {args.deck!r}")
        before = snapshot(col)
        preset_id = before[args.deck][0]
        preset_before = col.decks.get_config(preset_id)
        sharers = sorted(k for k, v in before.items() if v[0] == preset_id)
        eff = before[args.deck][2]
        eff = before[args.deck][1] if eff is None else eff
        print(f"{args.deck}: preset {preset_id} {preset_before['name']!r} "
              f"perDay={before[args.deck][1]} override={before[args.deck][2]} "
              f"-> effective {eff}/day")
        print(f"decks sharing that preset ({len(sharers)}): {sharers}")

        deck = col.decks.get(did)
        want = None if args.clear else args.per_day
        if args.clear:
            deck.pop("newLimit", None)
        else:
            deck["newLimit"] = args.per_day
        print(f"\n{args.deck} newLimit -> {want}")
        if not args.apply:
            print("DRY-RUN (pass --apply to write)")
            return

        col.decks.save(deck)

        after = snapshot(col)
        pb = {k: v for k, v in preset_before.items() if k not in ("mod", "usn")}
        pa = {k: v for k, v in col.decks.get_config(preset_id).items()
              if k not in ("mod", "usn")}
        assert pb == pa, "the shared preset changed -- restore from the anki_op backup"

        changed = [k for k in before if before[k] != after.get(k)]
        assert changed == [args.deck], f"expected only {args.deck}, got {changed}"
        assert after[args.deck][2] == want, after[args.deck]
        print(f"\nceilings after (preset {preset_id}):")
        for name in sharers:
            e = after[name][2] if after[name][2] is not None else after[name][1]
            mark = "  <-- changed" if name == args.deck else ""
            print(f"    {name:9s} perDay={after[name][1]:3d} override={after[name][2]}"
                  f"  effective {e}/day{mark}")
        print("\nVERIFIED: one deck changed; the shared preset is untouched.")
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
