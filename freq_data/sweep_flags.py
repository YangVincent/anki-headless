#!/usr/bin/env python3
"""Act on flags you set during review. Flag while studying, sweep later.

THE WORKFLOW. Anki flags are the only mark you can place mid-review on every device
(desktop Ctrl+1..7, AnkiMobile/AnkiDroid via the More menu). So:

    Orange  ->  push to the BACK of its deck's new queue  (tag `demoted` too)
    Purple  ->  SUSPEND, i.e. take it out of rotation entirely

Red and Blue are left untouched -- they are your existing "come back to this" pile
(45 and 13 cards), and this tool must not silently consume them.

The flag is CLEARED once acted on, so the pile never reprocesses and you can see at a
glance what is still waiting. Nothing is deleted: suspend and demote are both reversible.

A card already in learning or review has no new-queue position, so an Orange sweep also
forgets it back to new (that discards the card's scheduling, not the revlog). Pass
--no-reset to tag-and-leave instead.

  bash freq_data/anki_op.sh sweep freq_data/sweep_flags.py            # dry run
  bash freq_data/anki_op.sh sweep freq_data/sweep_flags.py --apply
"""
import sys
sys.path.insert(0, "/home/vincent/anki-headless")
import decks as deck_registry  # noqa: E402
import argparse
import sys

from anki.collection import Collection

COL = "/home/vincent/anki-headless/collection.anki2"
BACK, DROP = 2, 7                      # orange, purple
# The decks you actually study. Without this the sweep reaches Archive (213k cards),
# Cloze (17k) and Reverse (7.5k) too, because a flag is per-card and lives everywhere.
STUDY_DECKS = deck_registry.STUDY_DECKS
NAMES = {1: "Red", 2: "Orange", 3: "Green", 4: "Blue",
         5: "Pink", 6: "Turquoise", 7: "Purple"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-reset", action="store_true",
                    help="do not forget learning/review cards back to new")
    ap.add_argument("--deck", action="append",
                    help=f"deck to sweep, repeatable (default: {', '.join(STUDY_DECKS)}); "
                         f"--deck all sweeps every deck")
    ap.add_argument("--db", default=COL,
                    help="run against a scratch copy instead of the live collection")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    # This tool never syncs, so --db is safe here. resort_main_queue.py DID sync on --db
    # and pushed a scratch copy to AnkiWeb on 2026-08-31; do not add a sync to this one.
    col = Collection(args.db)
    try:
        deep = {}

        def deepest(did):
            if did not in deep:
                deep[did] = (col.db.scalar(
                    "SELECT MAX(due) FROM cards WHERE did=? AND type=0 AND ord=0", did)
                    or 16000) + 1
            return deep[did]

        wanted = args.deck or list(STUDY_DECKS)
        if wanted == ["all"]:
            dids, scope = None, "every deck"
        else:
            dids = [d for d in (col.decks.id_for_name(n) for n in wanted) if d]
            missing = [n for n in wanted if col.decks.id_for_name(n) is None]
            if missing:
                sys.exit(f"no such deck: {missing}")
            scope = ", ".join(wanted)
        print(f"sweeping: {scope}\n")
        sql = ("SELECT c.id, c.nid, c.did, c.type, c.queue, c.flags & 7, n.sfld "
               "FROM cards c JOIN notes n ON n.id = c.nid WHERE c.flags & 7 IN (?, ?)")
        params = [BACK, DROP]
        if dids is not None:
            sql += f" AND c.did IN ({','.join('?' * len(dids))})"
            params += dids
        rows = col.db.all(sql, *params)
        if not rows:
            print(f"nothing flagged {NAMES[BACK]} or {NAMES[DROP]}.")
            print(f"  flag {NAMES[BACK]} to push to the back, "
                  f"{NAMES[DROP]} to suspend, then run this again.")
            return

        moved = dropped = 0
        for cid, nid, did, typ, queue, flag, sfld in rows:
            dname = col.decks.name(did)
            word = sfld[:14]
            if flag == DROP:
                # Suspend every card of the note, not just the flagged one. A flag is
                # per-card; leaving the Reverse and Cloze siblings live would mean the
                # word you just removed keeps coming back on another template.
                sibs = col.db.list("SELECT id FROM cards WHERE nid=? AND queue>=0", nid)
                print(f"  SUSPEND  {word:14s} [{dname}] {len(sibs)} card(s) incl. siblings")
                if args.apply:
                    col.sched.suspend_cards(sibs)
                dropped += 1
            else:
                note = col.get_note(nid)
                if "demoted" not in [t.lower() for t in note.tags]:
                    if args.apply:
                        note.tags.append("demoted")
                        col.update_note(note)
                if typ != 0 and not args.no_reset:
                    if args.apply:
                        col.sched.schedule_cards_as_new([cid])
                    typ = 0
                if typ == 0:
                    pos = deepest(did)
                    if args.apply:
                        c = col.get_card(cid)
                        c.due = pos
                        col.update_card(c)
                    deep[did] += 1
                    print(f"  BACK     {word:14s} [{dname}] -> position {pos}")
                else:
                    print(f"  BACK     {word:14s} [{dname}] tagged only (still in review)")
                moved += 1
            if args.apply:                       # clear the flag once acted on
                col.set_user_flag_for_cards(0, [cid])

        print(f"\n{moved} pushed back, {dropped} suspended")
        if args.apply:
            # Verify with the SAME scope the sweep used. A collection-wide count fails
            # on flags this run deliberately skipped (e.g. one left in Archive).
            vsql = "SELECT count(*) FROM cards WHERE flags & 7 IN (?, ?)"
            vp = [BACK, DROP]
            if dids is not None:
                vsql += f" AND did IN ({','.join('?' * len(dids))})"
                vp += dids
            left = col.db.scalar(vsql, *vp)
            print(f"verify: cards still flagged {NAMES[BACK]}/{NAMES[DROP]} "
                  f"in {scope} = {left}")
            assert left == 0
            outside = col.db.scalar(
                "SELECT count(*) FROM cards WHERE flags & 7 IN (?, ?)", BACK, DROP)
            if outside:
                print(f"note: {outside} flagged card(s) outside {scope}, left alone "
                      f"(use --deck all to include them)")
            keep = col.db.scalar("SELECT count(*) FROM cards WHERE flags & 7 IN (1, 4)")
            print(f"verify: your Red/Blue pile untouched = {keep} cards")
            print("APPLIED")
        else:
            print("DRY-RUN (pass --apply)")
    finally:
        col.close()


if __name__ == "__main__":
    main()
