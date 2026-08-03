"""Return HSK 3.0 words to the HSK / HSK7-9 decks, by level.

The decks were missing 1,770 words the official standard contains. Almost none of them
were absent: 808 had a live card filed under non-HSK or Mined, and 954 had one suspended in
Hidden::Archive. Both are collateral from hsk_match.py, whose job is "make the HSK deck's
active set match the HSK 3.0 word list" — it ran against the corrupted hsk3_vocab.json,
failed to recognise these as HSK words, and swept them out. 752 of the archived ones are
HSK 7-9, matching that file's 7-9 band being 390 words short of the real one.

Destination is by official level: 1-6 -> HSK, 7-9 -> HSK7-9.

Only the ord=0 card of the best note moves. Preference is ChineseVocabulary, then
ChineseCharacters; the legacy "Basic - new hsk 3.0 xiehanzi v3 - *" notes are never moved,
because they are a different four-card writing system and dragging them in would change
what a card means. Words that only have those (165) and words with no card at all (8) are
reported for a separate card-building pass, not bodged in here.

Single characters Hanly already covers are excluded — that is the standing rule for this
deck. None of the archived ones are Hanly words anyway (checked: 0 of 269).

Suspended cards are unsuspended, since a suspended card is not in the list in any
meaningful sense. Cards that already have review history keep it and return at whatever
interval they had.

Usage: bash freq_data/anki_op.sh hsk-reinstate freq_data/hsk_reinstate_official.py --apply
"""
import argparse
import collections
import json
import re

from anki.collection import Collection

ROOT = "/home/vincent/anki-headless"
RANK = {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7-9": 7}
LEGACY = "Basic - new hsk 3.0 xiehanzi"


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    official = {e["word"]: e["level"]
                for e in json.load(open(f"{ROOT}/freq_data/hsk30_official.json"))}
    hanly = set(json.load(open(f"{ROOT}/hanly_current.json"))["known"])
    col = Collection(args.db)
    try:
        hsk = col.decks.id_for_name("HSK")
        hsk79 = col.decks.id_for_name("HSK7-9")
        src = {hsk, hsk79}

        present = set()
        for did in src:
            for nid, in col.db.all("SELECT DISTINCT nid FROM cards WHERE did=?", did):
                present.add(strip_html(col.get_note(nid).fields[0]))

        target = {w for w in official if not (len(w) == 1 and w in hanly)}
        missing = sorted(target - present, key=lambda w: (RANK[official[w]], w))

        moves = collections.defaultdict(list)   # dest_did -> [card ids]
        unsuspend, from_deck, needs_card = [], collections.Counter(), []
        with_history = 0
        for word in missing:
            cands = []
            for nid, in col.db.all("SELECT id FROM notes WHERE sfld=?", word):
                note = col.get_note(nid)
                name = note.note_type()["name"]
                if name.startswith(LEGACY):
                    continue
                for c in note.cards():
                    if c.ord == 0:
                        rank = 0 if name == "ChineseVocabulary" else 1 if name == "ChineseCharacters" else 2
                        cands.append((rank, c))
            cands = [c for c in cands if c[0] < 2]
            if not cands:
                needs_card.append(word)
                continue
            cands.sort(key=lambda t: (t[0], t[1].queue == -1))   # prefer right type, then live card
            card = cands[0][1]
            dest = hsk if RANK[official[word]] <= 6 else hsk79
            if card.did == dest and card.queue != -1:
                continue
            from_deck[col.decks.name(card.did)] += 1
            moves[dest].append(card.id)
            if card.queue == -1:
                unsuspend.append(card.id)
            if card.type != 0:
                with_history += 1

        total = sum(len(v) for v in moves.values())
        print(f"HSK 3.0 words missing from the decks: {len(missing)}")
        print(f"  reinstating: {total}  ->  HSK {len(moves[hsk])}, HSK7-9 {len(moves[hsk79])}")
        print(f"  of those, currently suspended: {len(unsuspend)}")
        print(f"  of those, carrying review history: {with_history}")
        print(f"  coming from: {dict(from_deck.most_common(8))}")
        print(f"  cannot place (legacy-only notes or no card): {len(needs_card)}")
        print(f"    {' '.join(needs_card[:20])}{' …' if len(needs_card) > 20 else ''}")

        if args.apply:
            for dest, cids in moves.items():
                col.set_deck(cids, dest)
            if unsuspend:
                col.sched.unsuspend_cards(unsuspend)
            still = 0
            present2 = set()
            for did in src:
                for nid, in col.db.all("SELECT DISTINCT nid FROM cards WHERE did=?", did):
                    present2.add(strip_html(col.get_note(nid).fields[0]))
            still = len(target - present2)
            print(f"\nverify: HSK 3.0 words still missing: {still} "
                  f"(expected {len(needs_card)} — the ones needing new cards)")
            wrong = 0
            for did, lvl_ok in ((hsk, lambda l: l <= 6), (hsk79, lambda l: l == 7)):
                for nid, in col.db.all("SELECT DISTINCT nid FROM cards WHERE did=?", did):
                    w = strip_html(col.get_note(nid).fields[0])
                    if w in official and not lvl_ok(RANK[official[w]]):
                        wrong += 1
            print(f"verify: words sitting in the wrong deck for their level: {wrong} (want 0)")
        else:
            print("\nDRY-RUN — nothing written.")
    finally:
        col.close()


if __name__ == "__main__":
    main()
