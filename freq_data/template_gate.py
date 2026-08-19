#!/usr/bin/env python3
"""Run the ChineseVocabulary maturity gates and report what changed.

Two templates are gated on the same rule: you should not drill a word in a harder
direction before you can recognise it.

  * ord 1 `English-Speaking` (say it in Mandarin)  -> the `Reverse` deck
  * ord 2 `Cloze-Recall`     (fill it in a blank)  -> the `Vocab Cloze` deck

Both stay suspended until the word's ord 0 recognition card matures (type=2,
interval >= 21 days) in a source deck, and neither ever sits in a study deck.

The rule itself lives in bot._apply_template_gate, so it exists in exactly one place.
This script only reports and verifies. The bot runs the same functions every 5 minutes
as part of periodic_sync; this script is the manual and cron entry point, and it runs
under anki_op.sh so a big batch gets a backup first.

Replaces freq_data/cloze_gate.py, which named a deck (`Vocab`) that had been renamed
away and so matched almost nothing and ran daily for months doing nothing. The production
side had the same defect in bot._sync_reverse_cards, which searched `deck:hanly-reverse`
after that deck became `Hidden::hanly-reverse`.

Three modes:
  (no flag)  dry run   — report the plan, write nothing
  --verify   read-only — run the checks, exit non-zero on failure. Used by the daily cron.
  --apply    write     — run the rule, then the checks. Use through anki_op.sh.
"""
import sys, time
sys.path.insert(0, "/home/vincent/anki-headless")
import bot

APPLY = "--apply" in sys.argv
# --verify: run the checks only, write nothing, exit non-zero if any check fails. The bot
# applies the rule in-process every 5 minutes, so the daily cron only needs to confirm the
# result. Read-only means no bot restart and no backup window.
VERIFY_ONLY = "--verify" in sys.argv

col = None
for _ in range(30):
    try:
        col = bot.open_collection(); break
    except Exception:
        time.sleep(2)
if col is None:
    print("collection locked"); sys.exit(1)

GATES = (
    ("production", bot.apply_reverse_gate, bot.REVERSE_TEMPLATE,
     bot.REVERSE_DECK, bot.REVERSE_SOURCE_DECKS),
    ("cloze", bot.apply_cloze_gate, bot.CLOZE_TEMPLATE,
     bot.CLOZE_DECK, bot.CLOZE_SOURCE_DECKS),
)

try:
    cv = col.models.by_name(bot.CHINESE_VOCAB_NOTETYPE)
    hidden = bot._hidden_deck_ids(col)
    failed = False

    for label, gate, template, home, sources in GATES:
        ord_ = next((t["ord"] for t in cv["tmpls"] if t["name"] == template), None)
        home_did = col.decks.id_for_name(home)
        print(f"\n=== {label} cards — {template!r} -> {home!r} ===")
        if ord_ is None or home_did is None:
            print(f"  SKIPPED: no {template!r} template or no {home!r} deck")
            failed = True
            continue

        strays = {}
        for did, live, n in col.db.all(
                "SELECT c.did, c.queue!=-1, count(*) FROM cards c JOIN notes n ON n.id=c.nid "
                "WHERE c.ord=? AND n.mid=? AND c.odid=0 "   # skip filtered-deck loans
                "GROUP BY c.did, c.queue!=-1", ord_, cv["id"]):
            if did == home_did or (did in hidden and not live):
                continue
            e = strays.setdefault(col.decks.name(did), [0, 0])
            e[0] += n
            if live:
                e[1] += n
        if strays:
            print("  sitting outside the gate's home deck:")
            for name, (tot, live) in sorted(strays.items(), key=lambda kv: -kv[1][0]):
                print(f"     {name:28s} {tot:6d}  ({live} unsuspended)")

        if VERIFY_ONLY:
            continue
        r = gate(col, dry_run=not APPLY)
        if r.get("error"):
            print(f"  NOT RUN: {r['error']}")
            failed = True
            continue
        print(f"  mature words across {sources}: {r['mature_words']}")
        print("  plan:" if not APPLY else "  applied:")
        print(f"     move into {home!r}              : {r['moved']}")
        print(f"     unsuspend (word is mature)        : {r['unsuspended']}")
        print(f"     suspend (not mature, never studied): {r['suspended']}")

    if not APPLY and not VERIFY_ONLY:
        print("\nDRY RUN — nothing written. Add --apply to commit.")
        sys.exit(1 if failed else 0)

    # ── verify. Under --apply this runs before anki_op.sh restarts the bot. ──
    print("\nVERIFY")
    study = [d.id for d in col.decks.all_names_and_ids()
             if "Hidden" not in d.name and d.name != "Default"]
    for label, gate, template, home, sources in GATES:
        ord_ = next((t["ord"] for t in cv["tmpls"] if t["name"] == template), None)
        home_did = col.decks.id_for_name(home)
        if ord_ is None or home_did is None:
            continue
        ph = ",".join("?" * len(study))
        wrong_deck = col.db.scalar(
            f"SELECT count(*) FROM cards c JOIN notes n ON n.id=c.nid WHERE c.ord=? "
            f"AND n.mid=? AND c.did!=? AND c.did IN ({ph})",
            ord_, cv["id"], home_did, *study)
        stray_live = col.db.scalar(
            "SELECT count(*) FROM cards c JOIN notes n ON n.id=c.nid WHERE c.ord=? "
            "AND n.mid=? AND c.queue!=-1 AND c.did!=?", ord_, cv["id"], home_did)
        tot = col.db.scalar("SELECT count(*) FROM cards WHERE did=?", home_did)
        live = col.db.scalar("SELECT count(*) FROM cards WHERE did=? AND queue!=-1", home_did)
        print(f"  {home!r}: {tot} cards, {live} unsuspended")
        # Location checks alone certified a state that broke the gate's whole purpose: a
        # live card for a word that was never mature passed all of them. Check maturity.
        src = []
        for name in sources:
            src.extend(d.id for d in col.decks.all_names_and_ids()
                       if d.name == name or d.name.startswith(name + "::"))
        ph = ",".join("?" * len(src))
        mature = set(col.db.list(
            f"SELECT nid FROM cards WHERE (CASE WHEN odid!=0 THEN odid ELSE did END) "
            f"IN ({ph}) AND ord=0 AND type=2 AND ivl>=? AND queue!=-1", *src, bot.MATURE_IVL))
        live_immature = [
            cid for cid, nid, reps in col.db.all(
                "SELECT c.id, c.nid, c.reps FROM cards c JOIN notes n ON n.id=c.nid "
                "WHERE c.ord=? AND n.mid=? AND c.queue!=-1", ord_, cv["id"])
            if nid not in mature and reps == 0]
        print(f"     in a study deck: {wrong_deck} (want 0) | "
              f"unsuspended elsewhere: {stray_live} (want 0)")
        print(f"     unsuspended for a word that is NOT mature: {len(live_immature)} (want 0)")
        if wrong_deck or stray_live or live_immature:
            failed = True
    bad = col.db.scalar("SELECT count(*) FROM cards WHERE type IN (1,2,3) AND due<0")
    print(f"  cards with a corrupted schedule: {bad} (want 0)")
    sys.exit(1 if (failed or bad) else 0)
finally:
    col.close()
