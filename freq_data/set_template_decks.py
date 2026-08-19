#!/usr/bin/env python3
"""Declare where each card template's cards belong, using Anki's per-template deck override.

Without an override, EVERY card a note generates lands in the note's home deck. That is
why cards kept appearing in the wrong place and a repair job had to sweep them up:

  * 65 cloze cards appeared in `Default` when SentenceSimplifiedCloze was backfilled
    later -- the note's home deck at generation time, not `Vocab Cloze`.
  * every new note put its production card in `Mined`.
  * 146 production cards ended up inside `HSK`, 132 inside `HSK7-9`, 106 in `Mined::三体`.

With the override, Anki places the card correctly at generation time and the maturity
gate only has to decide suspension.

VERIFIED before writing: setting a template `did` does NOT move existing cards. A test on
a copy left all 42,356 existing ord-1 cards where they were, and a newly created note put
its ord-1 card straight into `Reverse`.

ord 0 deliberately has NO override: a word's recognition card belongs in whichever of
HSK / HSK7-9 / non-HSK / Mined the note is filed under, and that varies per note.

Idempotent. Dry-run unless --apply.
Run via: bash freq_data/anki_op.sh template-decks freq_data/set_template_decks.py --apply
"""
import sys, time
sys.path.insert(0, "/home/vincent/anki-headless")
import bot

APPLY = "--apply" in sys.argv

# (note type, template name, destination deck). Only where the destination is unambiguous.
# Destinations come from decks.py by ROLE. They were literals until 2026-08-19, and two of
# them (`Vocab Cloze`, `Hidden::Archive::*`) stopped existing hours later — re-running this
# script would have failed on a deck name it had itself been told to write.
import decks
OVERRIDES = [
    ("ChineseVocabulary", bot.REVERSE_TEMPLATE, decks.PRODUCTION),
    ("ChineseVocabulary", bot.CLOZE_TEMPLATE,   decks.CLOZE),
    ("ChineseCharacters", "TradRecognition",    decks.ARCHIVE),
    ("ChineseSentences",  "Listen-English",     decks.ARCHIVE),
]

col = None
for _ in range(30):
    try:
        col = bot.open_collection(); break
    except Exception:
        time.sleep(2)
if col is None:
    print("collection locked"); sys.exit(1)

try:
    changed, failed = 0, []
    for mname, tname, role in OVERRIDES:
        dname = decks.name_of(role)
        m = col.models.by_name(mname)
        if not m:
            print(f"  SKIP {mname}: note type not found"); failed.append(mname); continue
        t = next((t for t in m["tmpls"] if t["name"] == tname), None)
        if t is None:
            print(f"  SKIP {mname}/{tname}: template not found"); failed.append(tname); continue
        try:
            did = decks.deck_id_for(col, role)
        except decks.DeckMissing as e:
            print(f"  SKIP {mname}/{tname}: {e}"); failed.append(dname); continue

        current = t.get("did")
        where = col.db.all(
            "SELECT c.did, count(*) FROM cards c JOIN notes n ON n.id=c.nid "
            "WHERE c.ord=? AND n.mid=? GROUP BY c.did ORDER BY count(*) DESC LIMIT 3",
            t["ord"], m["id"])
        spread = ", ".join(f"{col.decks.name(d)}={n}" for d, n in where)
        print(f"  {mname}/{tname} (ord {t['ord']})")
        print(f"     override: {col.decks.name(current) if current else 'none'} -> {dname}")
        print(f"     existing cards stay put: {spread}")
        if current == did:
            print("     already set")
            continue
        if APPLY:
            t["did"] = did
            col.models.update_dict(m)
        changed += 1

    if not APPLY:
        print(f"\nDRY RUN — {changed} override(s) would change. Add --apply to commit.")
        sys.exit(1 if failed else 0)

    # ── verify, before anki_op.sh restarts the bot ────────────────────
    print("\nVERIFY")
    ok = True
    for mname, tname, role in OVERRIDES:
        dname = decks.name_of(role)
        m = col.models.by_name(mname)
        t = next((t for t in m["tmpls"] if t["name"] == tname), None) if m else None
        if t is None:
            continue
        got = t.get("did")
        good = got is not None and col.decks.name(got) == dname
        ok &= good
        print(f"  {'OK ' if good else 'BAD'} {mname}/{tname} -> "
              f"{col.decks.name(got) if got else 'none'}")
    for mname in ("ChineseVocabulary", "ChineseCharacters", "ChineseSentences",
                  "ChineseCharactersWriting"):
        m = col.models.by_name(mname)
        if m:
            t0 = m["tmpls"][0]
            print(f"  {'OK ' if t0.get('did') is None else 'BAD'} {mname}/{t0['name']} "
                  f"(ord 0) has NO override, as intended")
            ok &= t0.get("did") is None
    print(f"  cards in Default: {col.db.scalar('SELECT count(*) FROM cards WHERE did=1')} (want 0)")
    print(f"  corrupted schedules: "
          f"{col.db.scalar('SELECT count(*) FROM cards WHERE type IN (1,2,3) AND due<0')} (want 0)")
    sys.exit(0 if (ok and not failed) else 1)
finally:
    col.close()
