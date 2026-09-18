#!/usr/bin/env python3
"""Rebuild the scheduling state of cards whose review history survived a sync but whose
card row did not.

Cause: a write on this machine (resort_main_queue.py repositions every NEW card) uploaded
a stale card row while the study device still held unsynced answers. The revlog is
append-only, so every answer merged. The card row holds one value per card, so the
uploaded copy won and the card reverted to `new`. 62 cards carry that damage, the oldest
from 2026-06-08 and 12 from 2026-09-18.

This script reads each card's own revlog and puts the card back where its last answer
left it: learning step, review interval, reps, lapses, and the FSRS memory state that
Anki computes from the same history.

It syncs DOWN before it writes, so it cannot repeat the failure it repairs.

Usage: bash freq_data/anki_op.sh repair-sched freq_data/repair_lost_scheduling.py --apply
       (no --apply prints the plan and writes nothing; --db PATH runs on a scratch copy
        and never syncs)
"""
import os, sys, json, argparse, datetime

sys.path.insert(0, "/home/vincent/anki-headless")
from anki.collection import Collection
from anki.cards import FSRSMemoryState

ROOT = "/home/vincent/anki-headless"
COL = f"{ROOT}/collection.anki2"
CARD_TYPE_LRN, CARD_TYPE_REV = 1, 2
QUEUE_TYPE_LRN, QUEUE_TYPE_REV = 1, 2


def sync(col, label):
    auth_file = os.path.expanduser("~/.anki_auth")
    if not os.path.exists(auth_file):
        print(f"SYNC {label}: SKIPPED (~/.anki_auth missing)")
        return False
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
        print(f"SYNC {label}: *** FULL SYNC REQUIRED *** — stopping, nothing written.")
        return False
    print(f"SYNC {label}: ok (status={res.required})")
    return True


def plan_for(col, cid, steps_secs):
    """What the revlog says this card's state should be."""
    rows = col.db.all(
        "SELECT id, ease, ivl, lastIvl, factor, type FROM revlog "
        "WHERE cid=? AND ease>0 ORDER BY id", cid)
    if not rows:
        return None
    reps = len(rows)
    # a lapse is `Again` on a card that was already in review
    lapses = sum(1 for r in rows if r[1] == 1 and r[5] == 1)
    last_id, last_ease, last_ivl, last_lastivl, last_factor, last_type = rows[-1]
    ivl = last_ivl if last_ivl != 0 else last_lastivl
    answered = last_id / 1000.0
    factor = last_factor if last_factor and last_factor >= 1300 else 2500
    if ivl < 0:
        delay = min(steps_secs, key=lambda s: abs(s - (-ivl)))
        idx = steps_secs.index(delay)
        return dict(kind="learning", type=CARD_TYPE_LRN, queue=QUEUE_TYPE_LRN,
                    due=int(answered + delay), ivl=0, left=len(steps_secs) - idx,
                    reps=reps, lapses=lapses, factor=factor, delay=delay)
    if ivl > 0:
        day = int((answered - col.crt) / 86400) + ivl
        return dict(kind="review", type=CARD_TYPE_REV, queue=QUEUE_TYPE_REV,
                    due=day, ivl=ivl, left=0, reps=reps, lapses=lapses, factor=factor)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--db", default=COL)
    args = ap.parse_args()
    scratch = os.path.abspath(args.db) != os.path.abspath(COL)

    col = Collection(args.db)
    try:
        if args.apply and not scratch and not sync(col, "before"):
            return 1

        rows = col.db.all(
            "SELECT c.id, n.sfld FROM cards c JOIN notes n ON n.id=c.nid "
            "WHERE c.reps=0 AND c.type=0 "
            "AND EXISTS (SELECT 1 FROM revlog r WHERE r.cid=c.id AND r.ease>0)")
        print(f"{len(rows)} cards read as new but hold real answers\n")

        conf = col.decks.config_dict_for_deck_id(
            [d.id for d in col.decks.all_names_and_ids() if d.name == "Main"][0])
        steps = [int(m * 60) for m in conf["new"]["delays"]] or [60, 600, 3600]
        print(f"learning steps: {steps} seconds\n")

        done, skipped = [], []
        print(f"{'word':<9}{'state':<10}{'ivl':>6}{'reps':>6}{'lapses':>8}  due")
        for cid, word in sorted(rows, key=lambda r: r[1]):
            p = plan_for(col, cid, steps)
            if not p:
                skipped.append(word)
                continue
            if p["kind"] == "learning":
                when = datetime.datetime.fromtimestamp(p["due"]).strftime("%Y-%m-%d %H:%M")
                shown = f"learn/{p['delay']//60}m"
            else:
                when = (datetime.date.fromtimestamp(col.crt)
                        + datetime.timedelta(days=p["due"])).isoformat()
                shown = "review"
            print(f"{word:<9}{shown:<10}{p['ivl']:>6}{p['reps']:>6}{p['lapses']:>8}  {when}")
            if not args.apply:
                continue
            card = col.get_card(cid)
            card.type, card.queue = p["type"], p["queue"]
            card.due, card.ivl, card.left = p["due"], p["ivl"], p["left"]
            card.reps, card.lapses, card.factor = p["reps"], p["lapses"], p["factor"]
            ms = col.compute_memory_state(cid)
            if ms and ms.stability:
                card.memory_state = FSRSMemoryState(
                    stability=ms.stability, difficulty=ms.difficulty)
            col.update_card(card)
            done.append((word, cid))

        if not args.apply:
            print(f"\nDRY RUN — would repair {len(rows) - len(skipped)}, skip {skipped}")
            return 0

        # verify inside this window, before the bot restarts
        bad = []
        for word, cid in done:
            c = col.get_card(cid)
            if c.type == 0 or c.reps == 0:
                bad.append((word, c.type, c.queue, c.reps))
        print(f"\nrepaired {len(done)}, skipped {len(skipped)} {skipped}")
        print(f"VERIFY: {'every card left the new state' if not bad else f'PROBLEMS {bad}'}")
        still = col.db.scalar(
            "SELECT count(*) FROM cards c WHERE c.reps=0 AND c.type=0 "
            "AND EXISTS (SELECT 1 FROM revlog r WHERE r.cid=c.id AND r.ease>0)")
        print(f"VERIFY: cards still reading new with real answers: {still} (want 0)")
        if not scratch:
            sync(col, "after")
        return 0 if not bad and still == 0 else 1
    finally:
        col.close()


if __name__ == "__main__":
    sys.exit(main())
