#!/usr/bin/env python3
"""Run the staged ChineseVocabulary Reverse gate and report what changed.

Durable ord 0 `Hanzi-English` recall unlocks ord 1 `English-Speaking` in
`Reverse`; flagging ord 0 overrides the mastery requirement. Cloze practice
is retired and is no longer released by this script or the bot.

Each transition is persisted as a note tag. Clearing the source flag later does not
automatically remove an already-unlocked card, and a card with review history is never
suspended by the gate. A card the user later suspends stays suspended: only a newly
created stage tag releases a card.

The rule itself lives in bot._apply_template_gate, so it exists in exactly one place.
This script only reports and verifies. The bot runs the same functions every 5 minutes
as part of periodic_sync; this script is the manual and cron entry point, and it runs
under anki_op.sh so a big batch gets a backup first.

Replaces freq_data/cloze_gate.py, which named a deck (`Vocab`) that had been renamed
away and so matched almost nothing and ran daily for months doing nothing. The production
side had the same defect in bot._sync_reverse_cards, which searched `deck:hanly-reverse`
after that deck became `Hidden::hanly-reverse` (now folded into `Archive`).

Three modes:
  (no flag)  dry run   — report the plan, write nothing
  --verify   read-only — run the checks, exit non-zero on failure. Used by the daily cron.
  --apply    write     — run the rule, then the checks. Use through anki_op.sh.
"""
import sys, time
sys.path.insert(0, "/home/vincent/anki-headless")
import bot
import decks

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

# Driven by ROLE. The names below are pulled from decks.py only to print them.
GATES = ((decks.PRODUCTION, bot.apply_reverse_gate, bot.REVERSE_TEMPLATE),)

try:
    cv = col.models.by_name(bot.CHINESE_VOCAB_NOTETYPE)
    hidden = bot._archive_deck_ids(col)
    failed = False

    for role, gate, template in GATES:
        label, home = role, decks.name_of(role)
        sources = decks.gate_sources(role)   # names, for the report line only
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
        print(f"  source: {r['source_template']} across {sources}")
        print(f"  flagged source cards: {r['source_flagged']}")
        print(f"  mastery-qualified cards: {r['source_mastered']}")
        print(f"  eligible source cards: {r['eligible_sources']}")
        print(f"  staged words: {r['staged_words']} ({r['newly_staged']} new)")
        print("  plan:" if not APPLY else "  applied:")
        print(f"     move into {home!r}              : {r['moved']}")
        print(f"     unsuspend (stage unlocked)         : {r['unsuspended']}")
        print(f"     suspend (not staged, never studied): {r['suspended']}")
        print(f"     append flagged to FIFO queue         : {r['repositioned_front']}")
        print(f"     reposition automatic behind queue   : {r['repositioned_back']}")

    if not APPLY and not VERIFY_ONLY:
        print("\nDRY RUN — nothing written. Add --apply to commit.")
        sys.exit(1 if failed else 0)

    # ── verify. Under --apply this runs before anki_op.sh restarts the bot. ──
    print("\nVERIFY")
    archived = bot._archive_deck_ids(col)
    study = [d.id for d in col.decks.all_names_and_ids()
             if d.id not in archived and d.name != decks.name_of(decks.RESERVED)]
    for role, gate, template in GATES:
        label, home = role, decks.name_of(role)
        sources = decks.gate_sources(role)   # names, for the report line only
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
        stage_tag = bot.STAGE_TAG_BY_TEMPLATE[template]
        live_unstaged = col.db.list(
            "SELECT c.id FROM cards c JOIN notes n ON n.id=c.nid "
            "WHERE c.ord=? AND n.mid=? AND c.queue!=-1 AND c.reps=0 "
            "AND n.tags NOT LIKE ?", ord_, cv["id"], f"% {stage_tag} %")
        print(f"     in a study deck: {wrong_deck} (want 0) | "
              f"unsuspended elsewhere: {stray_live} (want 0)")
        print(f"     unsuspended but not staged: {len(live_unstaged)} (want 0)")
        if wrong_deck or stray_live or live_unstaged:
            failed = True
    bad = col.db.scalar("SELECT count(*) FROM cards WHERE type IN (1,2,3) AND due<0")
    print(f"  cards with a corrupted schedule: {bad} (want 0)")
    sys.exit(1 if (failed or bad) else 0)
finally:
    col.close()
