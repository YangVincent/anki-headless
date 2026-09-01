#!/usr/bin/env python3
"""Refit FSRS to the HSK deck's own review history, and lower the retention target.

Two changes, HSK preset only:
  * fsrsParams6 refitted on the review history of whatever preset the recognition
    deck uses (the optimizer is re-run here
    rather than pasting numbers in, so the change is reproducible)
  * desiredRetention 0.93 -> 0.90

Everything else in the preset is left exactly as it is, and that is verified by a full
recursive diff before the write is allowed to stand — stock defaults quietly differ from
his settings on new.order, learning steps and autoplay, so a preset must never be
rebuilt, only edited in place. Existing cards keep their due dates; the new spacing
applies as each card next comes up.

Also snapshots how the deck is performing right now, split into the two populations that
behave differently (words known on sight vs words being learned), so the effect on the
hard words can actually be measured later instead of guessed at.

  fsrs_tune.py                     # dry run against a copy
  fsrs_tune.py --apply             # via freq_data/anki_op.sh
  fsrs_tune.py --report            # re-measure and compare to the baseline
"""
import sys
sys.path.insert(0, "/home/vincent/anki-headless")
import decks as deck_registry  # noqa: E402
import argparse
import copy
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path("/home/vincent/anki-headless")
COL = ROOT / "collection.anki2"
# The preset and the deck are resolved, never spelled. Both were renamed to `Main` on
# 2026-09-01, and a stale literal here would refit nothing while reporting success.
DECK = deck_registry.RECOGNITION_DECKS[0]

NEW_RETENTION = 0.90
BASELINE = ROOT / "freq_data/fsrs_baseline.json"


def measure(col):
    """How the HSK deck is actually performing, split by population."""
    did = col.decks.id_for_name(DECK)
    rows = col.db.all("select r.cid, r.id, r.ease, r.type, r.lastIvl "
                      "from revlog r join cards c on c.id=r.cid "
                      "where c.did=? order by r.cid, r.id", did)
    first, per = {}, defaultdict(lambda: [0, 0])
    groups = defaultdict(lambda: [0, 0])
    buckets = defaultdict(lambda: [0, 0])
    for cid, _rid, ease, typ, livl in rows:
        if typ in (0, 1, 2) and cid not in first:
            first[cid] = ease
    for cid, _rid, ease, typ, livl in rows:
        if typ != 1:
            continue
        failed = ease == 1
        per[cid][0] += 1
        per[cid][1] += failed
        g = ("knew on sight" if first.get(cid) == 4 else
             "had to learn" if first.get(cid) == 1 else "other")
        groups[g][0] += 1
        groups[g][1] += failed
        b = ("1d or less" if livl <= 1 else "2-7d" if livl <= 7 else
             "8-30d" if livl <= 30 else "31-90d" if livl <= 90 else "over 90d")
        buckets[b][0] += 1
        buckets[b][1] += failed

    def ret(pair):
        r, a = pair
        return round(1 - a / r, 4) if r else None

    worst = sorted(per.items(), key=lambda kv: -kv[1][1])[:25]
    return {
        "date": date.today().isoformat(),
        "cards_reviewed": len(per),
        "reviews": sum(v[0] for v in per.values()),
        "lapses": sum(v[1] for v in per.values()),
        "retention_overall": ret([sum(v[0] for v in per.values()),
                                  sum(v[1] for v in per.values())]),
        "retention_by_group": {k: {"retention": ret(v), "reviews": v[0]}
                               for k, v in groups.items()},
        "retention_by_interval": {k: {"retention": ret(v), "reviews": v[0]}
                                  for k, v in buckets.items()},
        "hard_words": [{"word": col.get_card(cid).note()["Simplified"],
                        "lapses": v[1], "reviews": v[0]} for cid, v in worst],
    }


def show(m, label):
    print(f"[{label}  {m['date']}]  {m['reviews']} reviews on {m['cards_reviewed']} cards, "
          f"{m['retention_overall']:.1%} remembered")
    for k, v in sorted(m["retention_by_group"].items()):
        print(f"     {k:<14} {v['retention']:.1%}  ({v['reviews']} reviews)")


def diff(a, b, path=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            out += diff(a.get(k, "<missing>"), b.get(k, "<missing>"), f"{path}.{k}" if path else k)
    elif a != b:
        sa, sb = str(a), str(b)
        out.append(f"{path}: {sa[:70]} -> {sb[:70]}")
    return out


def main():
    from anki.collection import Collection

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", action="store_true",
                    help="re-measure and compare against the saved baseline")
    ap.add_argument("--col", default=str(COL))
    a = ap.parse_args()
    if a.apply and a.col != str(COL):
        raise SystemExit("--apply only ever writes the real collection")

    col = Collection(a.col)
    try:
        now = measure(col)

        if a.report:
            show(now, "now")
            if not BASELINE.exists():
                print("no baseline saved — nothing to compare against")
                return
            was = json.loads(BASELINE.read_text())
            show(was, "baseline")
            print("\nchange since the settings were applied:")
            for k in sorted(set(now["retention_by_group"]) & set(was["retention_by_group"])):
                d = (now["retention_by_group"][k]["retention"]
                     - was["retention_by_group"][k]["retention"])
                print(f"     {k:<14} {d:+.1%}")
            old = {h["word"] for h in was["hard_words"]}
            still = [h for h in now["hard_words"] if h["word"] in old]
            print(f"\n{len(still)} of the {len(old)} worst words are still in the worst 25")
            return

        cfg = col.decks.config_dict_for_deck_id(col.decks.id_for_name(DECK))
        # The preset comes FROM the deck, not from a constant. It used to be asserted
        # against a literal "HSK"; that literal named a preset renamed to `Main` on
        # 2026-09-01, so the assert would have stopped the refit rather than doing it.
        # Reading it from the deck cannot go stale, and printing it keeps the operator
        # able to see which history is about to be fitted.
        preset = cfg["name"]
        before = copy.deepcopy(cfg)

        print(f'refitting on preset:"{preset}" review history — the preset {DECK!r} uses …')
        res = col._backend.compute_fsrs_params(
            search=f'preset:"{preset}"', current_params=list(cfg["fsrsParams6"]),
            ignore_revlogs_before_ms=0,
            num_of_relearning_steps=len(cfg["lapse"]["delays"]), health_check=True)
        if not res.health_check_passed:
            raise SystemExit("optimizer health check FAILED — not applying")
        params = [round(x, 4) for x in res.params]
        print(f"  fitted on {res.fsrs_items} reviews, health check passed")
        print(f"  before: {[round(x,4) for x in before['fsrsParams6']]}")
        print(f"  after : {params}")
        print(f"  retention: {before['desiredRetention']} -> {NEW_RETENTION}")

        cfg["fsrsParams6"] = params
        cfg["desiredRetention"] = NEW_RETENTION

        # nothing else may have moved
        changed = [d for d in diff(before, cfg)
                   if not d.startswith(("fsrsParams6", "desiredRetention", "mod", "usn"))]
        if changed:
            raise SystemExit("ABORT — unexpected changes to the preset:\n  " +
                             "\n  ".join(changed))
        print("  full preset diff: only fsrsParams6 and desiredRetention ✓")

        show(now, "baseline")
        if not a.apply:
            print("\n(dry run — nothing written)")
            return

        col.decks.update_config(cfg)
        after = col.decks.config_dict_for_deck_id(col.decks.id_for_name(DECK))
        assert list(after["fsrsParams6"]) == params, "params did not stick"
        assert after["desiredRetention"] == NEW_RETENTION, "retention did not stick"
        assert after["new"]["delays"] == before["new"]["delays"], "learning steps moved"
        assert after["new"]["perDay"] == before["new"]["perDay"], "new/day moved"
        print("\nwritten and verified.")

        BASELINE.write_text(json.dumps(now, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"baseline saved to {BASELINE.name} — re-run with --report in a few weeks")

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
    finally:
        col.close()


if __name__ == "__main__":
    main()
