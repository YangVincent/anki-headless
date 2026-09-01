#!/usr/bin/env python3
"""Put every `liked` word in the deck it belongs in, live and near the front.

A liked card's placement is owned by this script. Official HSK 3.0 words go to the HSK
deck; everything else goes to the other deck. Both names are flags -- they are this
collection's, not a rule. A card already in the right deck, unsuspended, is left alone.

THREE FAULTS THIS EXISTS TO PREVENT, all of them made here first:

  * like.py tagged and repositioned but its unsuspend did not stick, leaving cards
    marked and ordered yet unstudiable. Placement is verified after the write, per card.

  * An early version sent every liked word to HSK. That put 12 non-syllabus words
    (内疚, 忐忑, 诚然 ...) into the deck whose whole purpose is the official list.
    Routing comes from hsk30_official.json, never from where a card happens to sit.

  * Its successor only compared against the two home decks, so 17 cards stranded in a
    THIRD deck were reported as "nothing to move" -- a silent no-op. There is no
    opt-in reconcile flag now: a liked card is moved whenever it is not where it
    belongs, and --keep is the only exception.

  bash freq_data/anki_op.sh liked freq_data/activate_liked.py --apply
  ... --hsk-deck HSK --other-deck Mined --keep "Stella An"
"""
import argparse
import json

from anki.collection import Collection

COL = "/home/vincent/anki-headless/collection.anki2"
OFFICIAL = "/home/vincent/anki-headless/freq_data/hsk30_official.json"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hsk-deck", default="HSK",
                    help="where official HSK 3.0 words go (default: HSK)")
    ap.add_argument("--other-deck", default="Mined",
                    help="where every other liked word goes (default: Mined)")
    ap.add_argument("--keep", action="append",
                    help="a deck a liked card may stay in (repeatable; "
                         "default: 'Stella An')")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    keep_names = args.keep if args.keep is not None else ["Stella An"]

    official = {x["word"] for x in json.load(open(OFFICIAL, encoding="utf-8"))}
    col = Collection(COL)
    try:
        homes = {}
        for label, name in (("hsk", args.hsk_deck), ("other", args.other_deck)):
            did = col.decks.id_for_name(name)
            if did is None:
                raise SystemExit(f"no deck named {name!r}")
            homes[label] = did
        keep = {col.decks.id_for_name(k) for k in keep_names} - {None}
        print(f"official -> {args.hsk_deck} | other -> {args.other_deck} | "
              f"keep: {sorted(keep_names)}")

        cv = col.models.by_name("ChineseVocabulary")
        move, wake, ok = [], [], 0
        for nid in col.models.nids(cv["id"]):
            n = col.get_note(nid)
            if "liked" not in [t.lower() for t in n.tags]:
                continue
            row = col.db.first(
                "SELECT id, did, queue FROM cards WHERE nid=? AND ord=0", nid)
            if not row:
                continue
            cid, did, queue = row
            w = n.fields[0].strip()
            want = homes["hsk"] if w in official else homes["other"]
            if did in keep:
                if queue == -1:
                    wake.append((cid, w, col.decks.name(did)))
                else:
                    ok += 1
                continue
            if did != want:
                move.append((cid, w, col.decks.name(did), want, queue))
            elif queue == -1:
                wake.append((cid, w, col.decks.name(did)))
            else:
                ok += 1

        print(f"\nalready correct: {ok}")
        print(f"to move: {len(move)}")
        for cid, w, d, want, q in move:
            print(f"   {w:6s} {d} -> {col.decks.name(want)}"
                  f"{'  (suspended)' if q == -1 else ''}"
                  f"{'' if w in official else '   [not official]'}")
        print(f"to unsuspend in place: {len(wake)}")
        for cid, w, d in wake:
            print(f"   {w:6s} in {d}")
        if not args.apply:
            print("\nDRY-RUN (pass --apply)")
            return
        if not move and not wake:
            print("nothing to do")
            return

        by_deck = {}
        for cid, w, d, want, q in move:
            by_deck.setdefault(want, []).append(cid)
        for want, group in by_deck.items():
            col.set_deck(group, want)
        col.sched.unsuspend_cards([c for c, *_ in move] + [c for c, *_ in wake])

        # front of the queue, in each destination
        for want, group in by_deck.items():
            lo = col.db.scalar(
                "SELECT MIN(due) FROM cards WHERE did=? AND type=0 AND ord=0", want) or 1
            pos = lo - len(group)
            for cid in group:
                c = col.get_card(cid)
                if c.type == 0:
                    c.due = pos
                    col.update_card(c)
                pos += 1

        # verify every liked card, not just the ones touched
        bad = []
        for nid in col.models.nids(cv["id"]):
            n = col.get_note(nid)
            if "liked" not in [t.lower() for t in n.tags]:
                continue
            row = col.db.first(
                "SELECT did, queue FROM cards WHERE nid=? AND ord=0", nid)
            if not row:
                continue
            did, queue = row
            w = n.fields[0].strip()
            want = homes["hsk"] if w in official else homes["other"]
            if queue == -1:
                bad.append((w, "still suspended"))
            elif did not in keep and did != want:
                bad.append((w, f"in {col.decks.name(did)}, wanted "
                               f"{col.decks.name(want)}"))
        print(f"\nmoved {len(move)}, unsuspended {len(move) + len(wake)}, "
              f"problems {len(bad)}")
        for w, why in bad:
            print(f"   FAIL {w}: {why}")
        assert not bad
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
