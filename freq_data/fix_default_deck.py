#!/usr/bin/env python3
"""Empty the `Default` deck by sending each card to the deck it belongs in.

Cards landed in `Default` because bot.py's add_chinese_vocab asked Anki for a deck
named `Knowledge::Languages::Chinese::Vocabulary`, which this collection dropped.
id_for_name returned None and Anki fell back to `Default`. That cause is fixed in
bot.py; this script cleans up what accumulated.

Two groups, two homes:
  * ord 0 `Hanzi-English` -> `Mined`, repositioned to the front. They are tagged `mined`
    already: words looked up while reading. Their old positions are ~1,004,256, far
    behind Mined's -4..3,980 queue, so leaving them there would bury them forever. They
    go to positions 1..64 — behind the most recent wild adds, ahead of the shuihu block.
    Existing cards are NOT shifted.
  * ord 2 `Cloze-Recall`  -> `Vocab Cloze`, suspended. Their forward card already lives
    in HSK / HSK7-9 / non-HSK, so these were bypassing the maturity gate entirely.

Idempotent. Dry-run unless --apply.
Run via: bash freq_data/anki_op.sh fix-default freq_data/fix_default_deck.py --apply
"""
import sys, time
sys.path.insert(0, "/home/vincent/anki-headless")
import bot

APPLY = "--apply" in sys.argv
DEFAULT_DID = 1
import decks
# By role, not by name: `Vocab Cloze` was renamed `Cloze` hours after this script ran, and
# a literal here would have silently left every ord-2 card behind on a re-run.
# ord -> the ROLE that owns that template's cards. Resolved to ids at run time.
TARGETS = {0: "new_words", 2: decks.CLOZE}
SUSPEND_ORDS = {2}

col = None
for _ in range(30):
    try:
        col = bot.open_collection(); break
    except Exception:
        time.sleep(2)
if col is None:
    print("collection locked"); sys.exit(1)

try:
    rows = col.db.all(
        "SELECT c.id, c.ord, c.queue, c.type, c.due, c.reps FROM cards c WHERE c.did=?",
        DEFAULT_DID)
    print(f"'Default': {len(rows)} cards, "
          f"{sum(1 for r in rows if r[2] != -1)} unsuspended, "
          f"{sum(1 for r in rows if r[5] > 0)} ever reviewed")
    if not rows:
        print("nothing to do"); sys.exit(0)

    by_ord = {}
    for cid, o, q, t, due, reps in rows:
        by_ord.setdefault(o, []).append((cid, q, t, due, reps))

    plan, unknown = {}, []
    for o, cards in sorted(by_ord.items()):
        role = TARGETS.get(o)
        name = None if role is None else (
            decks.NEW_WORDS_DECK if role == "new_words" else decks.name_of(role))
        dues = sorted(c[3] for c in cards if c[2] == 0)
        span = f"queue positions {dues[0]}..{dues[-1]}" if dues else "no new cards"
        if name is None:
            unknown.append(o)
            print(f"  ord {o}: {len(cards)} cards -> NO TARGET, left alone ({span})")
            continue
        try:
            did = (decks.new_words_deck_id(col) if role == "new_words"
                   else decks.deck_id_for(col, role))
        except decks.DeckMissing:
            did = None
        if did is None:
            unknown.append(o)
            print(f"  ord {o}: {len(cards)} cards -> deck {name!r} MISSING, left alone")
            continue
        reviewed = sum(1 for c in cards if c[4] > 0)
        print(f"  ord {o}: {len(cards)} cards -> {name!r}"
              + (", suspended" if o in SUSPEND_ORDS else "")
              + f"  ({span}, {reviewed} ever reviewed)")
        plan[did] = plan.get(did, []) + [c[0] for c in cards]
        if o in SUSPEND_ORDS:
            plan.setdefault("_suspend", []).extend(c[0] for c in cards)

    if dues := sorted(c[3] for cards in by_ord.values() for c in cards if c[2] == 0):
        mined = decks.new_words_deck_id(col)
        lo = col.db.scalar(
            "SELECT MIN(due) FROM cards WHERE did=? AND type=0 AND ord=0", mined)
        hi = col.db.scalar(
            "SELECT MAX(due) FROM cards WHERE did=? AND type=0 AND ord=0", mined)
        print(f"\n  'Mined' new queue currently spans positions {lo}..{hi}")

    if not APPLY:
        print("\nDRY RUN — nothing written. Add --apply to commit.")
        sys.exit(0)

    to_suspend = plan.pop("_suspend", [])
    for did, cids in plan.items():
        col.set_deck(cids, did)
    if to_suspend:
        col.sched.suspend_cards(to_suspend)

    # `due` on a new card is a queue POSITION. These sat at ~1,004,256 while Mined's
    # queue ends at 3,980, so without this they would never come up. shift_existing is
    # False: nothing else in Mined moves.
    forward = [c[0] for c in by_ord.get(0, []) if c[2] == 0]
    if forward:
        r = col.sched.reposition_new_cards(forward, starting_from=1, step_size=1,
                                           randomize=False, shift_existing=False)
        print(f"\nrepositioned {r.count} forward card(s) to the front of 'Mined'")

    # ── verify before anki_op.sh restarts the bot ─────────────────────
    left = col.db.scalar("SELECT count(*) FROM cards WHERE did=?", DEFAULT_DID)
    print(f"\nVERIFY")
    print(f"  cards left in 'Default': {left}  (want {len(unknown) and 'only untargeted' or 0})")
    for name in sorted(set(TARGETS.values())):
        try:
            did = (decks.new_words_deck_id(col) if role == "new_words"
                   else decks.deck_id_for(col, role))
        except decks.DeckMissing:
            did = None
        if did is None:
            continue
        tot = col.db.scalar("SELECT count(*) FROM cards WHERE did=?", did)
        live = col.db.scalar("SELECT count(*) FROM cards WHERE did=? AND queue!=-1", did)
        print(f"  {name!r}: {tot} cards, {live} unsuspended")
    print("  cards with a corrupted schedule: "
          + str(col.db.scalar("SELECT count(*) FROM cards WHERE type IN (1,2,3) AND due<0"))
          + "  (want 0)")
finally:
    col.close()
