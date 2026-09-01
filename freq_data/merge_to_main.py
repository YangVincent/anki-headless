#!/usr/bin/env python3
"""One-off migration: HSK + Mined + Stella An -> a single `Main` deck.

Vincent studies one direction only, so the recognition split earned nothing. This makes
the roster `Main`, `Reverse`, `Cloze`, `Archive`, `Default`.

  1. move Mined's and Stella An's cards into HSK
  2. tag Stella An's notes `next::stella-an`, so the resort can place them right after
     the `liked` block rather than at the back with the level-9 fallback
  3. rename the deck HSK -> Main, and the preset it uses -> Main
  4. delete Mined, Stella An, non-HSK and HSK7-9, each only after proving it is empty
  5. rewrite decks.py's roster, inside this same window, so anki-bot restarts into a
     collection and a registry that agree

NAMES ARE LITERAL HERE, and only here. decks.py exists so nothing else spells a deck
name, but a migration that renames the decks cannot resolve them by the roles it is
about to redefine. Every other script keeps asking for roles.

THE PRESET IS RENAMED, NEVER RECREATED. add_config() would hand back Anki's stock
defaults -- new.order, fsrsParams6, autoplay -- which has silently wrecked this
collection's scheduler before. The rename is verified by a full recursive diff that
accepts only `name`, `mod` and `usn`.

Gates stay declared on Main. Emptying them is NOT how the gate was turned off: see
bot.GATE_DISABLED, and decks.gate_source_ids(), which refuses an empty source list
because it would suspend every released card while reporting success.

Usage: bash freq_data/anki_op.sh merge-main freq_data/merge_to_main.py --apply
"""
import argparse
import sys
from pathlib import Path

ROOT = Path("/home/vincent/anki-headless")
sys.path.insert(0, str(ROOT))

import anki.collection  # noqa: E402,F401
from anki.collection import Collection  # noqa: E402

KEEP = "HSK"                       # becomes Main
FOLD_IN = ("Mined", "Stella An")   # cards move into KEEP
DROP_EMPTY = ("non-HSK", "HSK7-9")  # deleted once proved empty
NEW_NAME = "Main"
STELLA_TAG = "next::stella-an"
DECKS_PY = ROOT / "decks.py"

OLD_ROSTER_HEAD = '''# ── the list ──────────────────────────────────────────────────────────
# Consolidated 2026-08-19, down from 26 decks. This is the whole collection.
DECKS = ('''

NEW_ROSTER = '''# ── the list ──────────────────────────────────────────────────────────
# Consolidated 2026-08-19 (26 decks -> 8), then again 2026-09-01 (8 -> 5). This is the
# whole collection. `HSK`, `HSK7-9`, `non-HSK` and `Mined` all became `Main`: Vincent
# studies one direction, so splitting the recognition role bought nothing and cost an
# ordering rule per deck.
DECKS = (
    # One recognition deck, and new words land in it. The `liked` / `next::` / `demoted`
    # / `book::` tags carry the ordering that four decks used to carry; see
    # freq_data/resort_main_queue.py.
    Deck("Main", RECOGNITION, gates=(PRODUCTION, CLOZE), new_words=True,
         legacy_names=("HSK", "HSK7-9", "non-HSK", "Mined", "Vocab"),
         note="Every word, Chinese -> English. HSK 3.0 and everything outside it."),
    # The gates stay DECLARED even though neither fires today. bot.GATE_DISABLED is the
    # off switch; an empty `gates` here is not, because gate_source_ids() refuses an
    # empty source list -- with no source, `mature` is empty and the gate would suspend
    # every released card while reporting success.
    Deck("Reverse", PRODUCTION,
         note="Production cards. All suspended 2026-09-01; the gate no longer releases."),
    Deck("Cloze", CLOZE, legacy_names=("Vocab Cloze",),
         note="Cloze cards. All suspended 2026-09-01; the gate no longer releases."),
    Deck("Archive", ARCHIVE, legacy_names=("Hidden",),
         note="Everything parked. Always suspended. Notes here must be promoted, "
              "never re-created."),
    Deck("Default", RESERVED,
         note="0 cards. Anki reserves deck id 1 and will not let it be deleted."),
)'''


def diff_config(before, after):
    """Keys whose value changed, recursively."""
    out = []
    for k in sorted(set(before) | set(after)):
        b, a = before.get(k), after.get(k)
        if isinstance(b, dict) and isinstance(a, dict):
            out.extend(f"{k}.{s}" for s in diff_config(b, a))
        elif b != a:
            out.append(k)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "collection.anki2"))
    ap.add_argument("--decks-py", default=str(DECKS_PY))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    col = Collection(args.db)
    try:
        keep_id = col.decks.id_for_name(KEEP)
        if keep_id is None:
            sys.exit(f"no deck named {KEEP!r}; already migrated?")
        cards_before, notes_before = col.card_count(), col.note_count()
        revlog_before = col.db.scalar("select count(*) from revlog")
        cfg_before = dict(col.decks.config_dict_for_deck_id(keep_id))

        print(f"{KEEP!r} holds {col.db.scalar('select count(*) from cards where did=?', keep_id)} cards")
        moves = []
        for name in FOLD_IN:
            did = col.decks.id_for_name(name)
            if did is None:
                print(f"  {name!r}: absent, skipped")
                continue
            cids = col.db.list("select id from cards where did=?", did)
            moves.append((name, did, cids))
            print(f"  {name!r}: {len(cids)} cards -> {KEEP!r}")
        drops = []
        for name in DROP_EMPTY:
            did = col.decks.id_for_name(name)
            if did is None:
                print(f"  {name!r}: absent, skipped")
                continue
            n = col.db.scalar("select count(*) from cards where did=?", did)
            drops.append((name, did, n))
            print(f"  {name!r}: {n} cards, delete once empty")
        print(f"\npreset {cfg_before['name']!r} -> {NEW_NAME!r}   "
              f"(new/day stays {cfg_before['new']['perDay']})")
        print(f"deck {KEEP!r} -> {NEW_NAME!r}")

        if not args.apply:
            print("\n(dry run; nothing written)")
            return

        # 1-2. move, and tag Stella An's notes
        for name, did, cids in moves:
            if not cids:
                continue
            col.set_deck(cids, keep_id)
            if name == "Stella An":
                nids = col.db.list("select distinct nid from cards where id in "
                                   f"({','.join('?' * len(cids))})", *cids)
                for nid in nids:
                    note = col.get_note(nid)
                    if STELLA_TAG not in note.tags:
                        note.add_tag(STELLA_TAG)
                        col.update_note(note)
                print(f"  tagged {len(nids)} notes {STELLA_TAG}")

        # 3. rename the deck, then the preset it uses
        col.decks.rename(col.decks.get(keep_id), NEW_NAME)
        cfg = col.decks.config_dict_for_deck_id(keep_id)
        cfg["name"] = NEW_NAME
        col.decks.update_config(cfg)

        # 4. delete, only what is provably empty
        for name, did, _ in [(n, d, 0) for n, d, _ in moves] + drops:
            left = col.db.scalar("select count(*) from cards where did=?", did)
            if left:
                sys.exit(f"REFUSING to delete {name!r}: {left} cards still in it")
            col.decks.remove([did])
            print(f"  deleted {name!r} (was empty)")

        # 5. the registry, in this same window
        src = Path(args.decks_py).read_text(encoding="utf-8")
        start = src.index(OLD_ROSTER_HEAD)
        end = src.index("\n)", start) + 2
        Path(args.decks_py).write_text(src[:start] + NEW_ROSTER + src[end:], encoding="utf-8")
        print(f"  rewrote {args.decks_py}")

        # ── verify ──
        after = dict(col.decks.config_dict_for_deck_id(keep_id))
        changed = diff_config(cfg_before, after)
        ok = set(changed) <= {"name", "mod", "usn"}
        print(f"\nverify: preset keys changed: {changed} "
              f"{'(only name/mod/usn)' if ok else '<-- UNEXPECTED'}")
        print(f"verify: {NEW_NAME} holds "
              f"{col.db.scalar('select count(*) from cards where did=?', keep_id)} cards")
        print(f"verify: cards {cards_before} -> {col.card_count()} (want unchanged)")
        print(f"verify: notes {notes_before} -> {col.note_count()} (want unchanged)")
        print(f"verify: revlog {revlog_before} -> "
              f"{col.db.scalar('select count(*) from revlog')} (want unchanged)")
        print("verify: decks now " +
              ", ".join(sorted(d.name for d in col.decks.all_names_and_ids())))
    finally:
        col.close()


if __name__ == "__main__":
    main()
