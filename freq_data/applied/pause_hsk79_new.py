"""Pause new cards in HSK7-9 without touching the preset six other decks share.

WHY A DECK-LEVEL LIMIT, NOT A PRESET EDIT. HSK7-9 sits on the preset named 'HSK'
(id 1783563765335), and so do Archive, Cloze, Default, Mined, Reverse and non-HSK.
Setting that preset's new.perDay to 0 would stop new cards in all seven decks. The v3
scheduler (sched2021=True here) honours a per-deck `newLimit`, so the change lands on
HSK7-9 alone.

Reversible: set --per-day back to 10, or clear the override with --clear.

Run through freq_data/anki_op.sh. Dry-run by default; pass --apply to write.
"""
import argparse
import sys

from anki.collection import Collection

COL = "/home/vincent/anki-headless/collection.anki2"
DECK = "HSK7-9"
SHARED_PRESET = 1783563765335


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
    ap.add_argument("--per-day", type=int, default=0)
    ap.add_argument("--clear", action="store_true", help="remove the override")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    col = Collection(COL)
    try:
        before = snapshot(col)
        preset_before = col.decks.get_config(SHARED_PRESET)
        print(f"{DECK} before: preset={before[DECK][0]} perDay={before[DECK][1]} "
              f"newLimit={before[DECK][2]}")
        print(f"decks sharing preset {SHARED_PRESET}: "
              f"{sorted(k for k, v in before.items() if v[0] == SHARED_PRESET)}")

        did = col.decks.id_for_name(DECK)
        deck = col.decks.get(did)
        if args.clear:
            deck.pop("newLimit", None)
            want = None
        else:
            deck["newLimit"] = args.per_day
            want = args.per_day
        print(f"\n{DECK} newLimit -> {want}")

        if not args.apply:
            print("DRY-RUN (pass --apply to write)")
            return

        col.decks.save(deck)

        after = snapshot(col)
        preset_after = col.decks.get_config(SHARED_PRESET)

        # The shared preset must be byte-identical apart from bookkeeping.
        pb = {k: v for k, v in preset_before.items() if k not in ("mod", "usn")}
        pa = {k: v for k, v in preset_after.items() if k not in ("mod", "usn")}
        assert pb == pa, "the shared preset changed -- restore from the anki_op backup"

        changed = [k for k in before if before[k] != after.get(k)]
        print(f"\ndecks whose new-card ceiling changed: {changed}")
        assert changed == [DECK], f"expected only {DECK}, got {changed}"
        assert after[DECK][2] == want, after[DECK]
        for name in sorted(k for k, v in after.items() if v[0] == SHARED_PRESET):
            print(f"    {name:9s} perDay={after[name][1]} newLimit={after[name][2]}")
        print("\nVERIFIED: only HSK7-9 changed; the shared preset is untouched.")
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
