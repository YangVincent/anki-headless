#!/usr/bin/env python3
"""Collapse the collection onto one flat, intended set of decks.

Before: 26 decks, 8 of them a `Hidden::` subtree holding 212,737 parked cards, plus two
`Mined::` subdecks, four empty decks and a stale filtered deck.

After:
    HSK, HSK7-9, non-HSK, Mined, Reverse   — the study decks
    Cloze                                  — renamed from `Vocab Cloze`
    Archive                                — everything parked, all suspended
    Default                                — 0 cards; Anki reserves deck id 1 and will
                                             not let it be deleted

Nothing is deleted. 67,744 notes exist ONLY in the archive (30,556 words, 7,506
characters, all 28,320 sentences, 1,362 writing notes), so the archive is moved, never
removed. A deck is only removed once it is empty, and the script asserts that.

THE INVARIANT: the total card count must be identical before and after. Anki's
decks.remove() deletes a deck AND its cards, so every removal is guarded.

bot.py already accepts both `Hidden` and `Archive` as archive names (ARCHIVE_DECK_NAMES),
so the gate behaves correctly before and after this runs.

Idempotent. Dry-run unless --apply.
Run via: bash freq_data/anki_op.sh consolidate freq_data/consolidate_decks.py --apply
"""
import sys, time
sys.path.insert(0, "/home/vincent/anki-headless")
import bot

APPLY = "--apply" in sys.argv
ARCHIVE = "Archive"
CLOZE_OLD, CLOZE_NEW = "Vocab Cloze", "Cloze"
KEEP = {"HSK", "HSK7-9", "non-HSK", "Mined", "Reverse", CLOZE_NEW, ARCHIVE, "Default"}
# Template overrides that name a deck this script dissolves.
REPOINT = [("ChineseCharacters", "TradRecognition", ARCHIVE),
           ("ChineseSentences", "Listen-English", ARCHIVE)]

col = None
for _ in range(30):
    try:
        col = bot.open_collection(); break
    except Exception:
        time.sleep(2)
if col is None:
    print("collection locked"); sys.exit(1)

try:
    def names():
        return {d.name: d.id for d in col.decks.all_names_and_ids()}

    total_before = col.db.scalar("SELECT count(*) FROM cards")
    notes_before = col.db.scalar("SELECT count(*) FROM notes")
    print(f"before: {len(names())} decks, {total_before} cards, {notes_before} notes\n")

    plan = []
    cur = names()

    # 1. Vocab Cloze -> Cloze
    if CLOZE_OLD in cur and CLOZE_NEW not in cur:
        plan.append(("rename", CLOZE_OLD, CLOZE_NEW,
                     col.db.scalar("SELECT count(*) FROM cards WHERE did=?", cur[CLOZE_OLD])))

    # 2. every Hidden:: deck and every Mined:: subdeck folds into one destination
    folds = []
    for name, did in sorted(cur.items()):
        n = col.db.scalar("SELECT count(*) FROM cards WHERE did=?", did)
        if name == "Hidden" or name.startswith("Hidden::"):
            folds.append((name, did, ARCHIVE, n))
        elif name.startswith("Mined::"):
            folds.append((name, did, "Mined", n))
    plan += [("fold", a, b, n) for a, _, b, n in folds]

    # 3. decks that end up empty and are not in KEEP
    for name, did in sorted(cur.items()):
        n = col.db.scalar("SELECT count(*) FROM cards WHERE did=?", did)
        folding = name == "Hidden" or name.startswith(("Hidden::", "Mined::"))
        if name not in KEEP and not folding and n == 0:
            plan.append(("remove-empty", name, "", 0))

    for kind, a, b, n in plan:
        print(f"  {kind:12s} {a:34s} {('-> ' + b) if b else '':24s} {n:7d} cards")
    print(f"\n  template overrides to repoint: "
          + ", ".join(f"{m}/{t} -> {d}" for m, t, d in REPOINT))

    if not APPLY:
        print("\nDRY RUN — nothing written. Add --apply to commit.")
        sys.exit(0)

    # ── apply ─────────────────────────────────────────────────────────
    if CLOZE_OLD in cur and CLOZE_NEW not in cur:
        col.decks.rename(col.decks.get(cur[CLOZE_OLD]), CLOZE_NEW)

    arch_did = col.decks.id_for_name(ARCHIVE) or col.decks.id(ARCHIVE)
    mined_did = bot.deck_id(col, "Mined")
    dests = {ARCHIVE: arch_did, "Mined": mined_did}

    to_suspend = []
    for name, did, dest, _ in folds:
        cids = col.db.list("SELECT id FROM cards WHERE did=?", did)
        if cids:
            col.set_deck(cids, dests[dest])
            if dest == ARCHIVE:
                to_suspend.extend(cids)
    if to_suspend:
        live = [c for c in to_suspend if col.get_card(c).queue != -1]
        if live:
            col.sched.suspend_cards(live)
            print(f"\n  suspended {len(live)} card(s) that were still live in the archive")

    # repoint template overrides BEFORE the decks they name disappear
    for mname, tname, dname in REPOINT:
        m = col.models.by_name(mname)
        if not m:
            continue
        t = next((t for t in m["tmpls"] if t["name"] == tname), None)
        if t is None:
            continue
        t["did"] = bot.deck_id(col, dname)
        col.models.update_dict(m)

    # remove decks, only when provably empty
    removed = []
    for name, did in sorted(names().items(), key=lambda kv: -kv[0].count("::")):
        if name in KEEP:
            continue
        n = col.db.scalar("SELECT count(*) FROM cards WHERE did=?", did)
        assert n == 0, f"refusing to remove {name!r}: still holds {n} cards"
        col.decks.remove([did])
        removed.append(name)
    print(f"  removed {len(removed)} empty deck(s)")

    # ── verify ────────────────────────────────────────────────────────
    print("\nVERIFY")
    total_after = col.db.scalar("SELECT count(*) FROM cards")
    notes_after = col.db.scalar("SELECT count(*) FROM notes")
    print(f"  cards {total_before} -> {total_after}   (must be equal: "
          f"{'OK' if total_before == total_after else 'MISMATCH'})")
    print(f"  notes {notes_before} -> {notes_after}   (must be equal: "
          f"{'OK' if notes_before == notes_after else 'MISMATCH'})")
    final = names()
    print(f"  decks: {sorted(final)}")
    extra = set(final) - KEEP
    print(f"  unexpected decks: {sorted(extra) or 'none'}")
    live_arch = col.db.scalar("SELECT count(*) FROM cards WHERE did=? AND queue!=-1", arch_did)
    print(f"  live cards in {ARCHIVE!r}: {live_arch} (want 0)")
    for mname, tname, dname in REPOINT:
        m = col.models.by_name(mname)
        t = next((t for t in m["tmpls"] if t["name"] == tname), None)
        got = col.decks.name(t["did"]) if t and t.get("did") else None
        print(f"  override {mname}/{tname} -> {got}")
    bad = col.db.scalar("SELECT count(*) FROM cards WHERE type IN (1,2,3) AND due<0")
    print(f"  corrupted schedules: {bad} (want 0)")
    orphan = col.db.scalar("SELECT count(*) FROM cards WHERE did NOT IN (SELECT id FROM decks)")
    print(f"  cards pointing at a missing deck: {orphan} (want 0)")
    ok = (total_before == total_after and notes_before == notes_after
          and not extra and live_arch == 0 and bad == 0 and orphan == 0)
    sys.exit(0 if ok else 1)
finally:
    col.close()
