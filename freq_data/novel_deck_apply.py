#!/usr/bin/env python3
"""Assemble a study deck for 十日终焉·囚笼 from the words the book actually repeats.

There are not 200 unstudied *new* words left in this book — only 31 dictionary words
that occur 3+ times have no card at all. What is missing is 200 words that already have
a card he has never seen, parked and suspended in Hidden::Archive. Those archived notes
already carry pinyin, a gloss and audio, so this gathers them rather than making
duplicates: it moves the Hanzi→English card into the novel deck, unsuspends it, and
orders the deck by how often the word occurs in the book.

Deliberately untouched:
  * the HSK and HSK7-9 decks. 704 book words sit unseen in HSK; they will come up in
    that queue on their own. Nothing is moved, unsuspended, repositioned or deleted
    there — the script asserts this before committing.
  * non-HSK, Vocab Cloze and every other active deck. 406 more book words sit unseen
    in those; reorganising an active queue is not what "make a deck" means.
  * the second card (English→Speaking) of each archived note, which stays suspended
    where it is, matching how the existing Mined deck is set up.

The new deck is assigned the existing Mined preset — never a fresh config, whose stock
defaults would silently reset new.order, FSRS params and autoplay.

  novel_deck_apply.py                # dry run: prints exactly what would change
  novel_deck_apply.py --apply        # via freq_data/anki_op.sh
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/home/vincent/anki-headless/freq_data")
from novel_deck_build import (BOOK, HAN, PROPER, cedict, hsk_levels,  # noqa: E402
                              known_words, pinyin_diacritic, sample_sentences)

ROOT = Path("/home/vincent/anki-headless")
COL = ROOT / "collection.anki2"
DECK = "Mined::十日终焉"
PRESET = "Mined"
TAGS = ["mined", "shiri-zhongyan"]
PROTECTED = ("HSK", "HSK7-9")      # never touched, asserted below
MIN_N = 3
NOTETYPE = "ChineseVocabulary"


def stars(n):
    """In-book frequency badge, same shape as the CustomFreq on existing Mined cards."""
    for lo, label in ((100, "★★★★★ everywhere in this book"), (40, "★★★★ very frequent"),
                      (15, "★★★ frequent"), (7, "★★ recurring")):
        if n >= lo:
            return f"{label} · {n}× in 囚笼"
    return f"★ occasional · {n}× in 囚笼"


def _sync(col):
    """Push to AnkiWeb so the phone has it before the next session."""
    from anki.sync import SyncAuth
    cred = json.loads(Path("~/.anki_auth").expanduser().read_text())
    auth = SyncAuth()
    auth.hkey = cred["hkey"]
    if cred.get("endpoint"):
        auth.endpoint = cred["endpoint"]
    out = col.sync_collection(auth, sync_media=False)
    print("  sync: " + {0: "nothing further to send", 1: "changes uploaded",
                        2: "FULL SYNC REQUIRED — resolve direction by hand"}
          .get(out.required, f"status {out.required}"))


def main():
    import jieba
    import jieba.posseg as pseg
    from anki.collection import Collection

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--col", default=str(COL),
                    help="dry-run against a copy so the bot can stay up")
    ap.add_argument("--dump-pool", metavar="JSON",
                    help="write the ranked pool (with book sentences) and stop — "
                         "input for novel_deck_screen.py")
    ap.add_argument("--exclude", metavar="JSON", default=str(ROOT / "freq_data/novel_deck_screen.json"),
                    help="screening output: words to drop (character names, non-words)")
    ap.add_argument("--refresh", action="store_true",
                    help="repair the existing deck's pinyin/sentences/badges in place; "
                         "moves nothing and creates nothing")
    a = ap.parse_args()
    if a.apply and a.col != str(COL):
        sys.exit("--apply only ever writes the real collection")

    text = BOOK.read_text(encoding="utf-8", errors="ignore")
    ced, hsk = cedict(), hsk_levels()
    known = known_words()
    counts = Counter(w for w in jieba.cut(text) if len(w) >= 2 and HAN.match(w))
    propers = {w for w, f in pseg.cut(text) if f.startswith(PROPER)}

    col = Collection(a.col)
    try:
        # ---- repair pass over a deck that already exists --------------------------
        if a.refresh:
            nids = col.find_notes(f'deck:"{DECK}"')
            words = []
            for nid in nids:
                words.append(col.get_note(nid)["Simplified"])
            sents = sample_sentences(text, words)
            fixed = Counter()
            for nid in nids:
                note = col.get_note(nid)
                w = note["Simplified"]
                if re.search(r"[1-5]", note["Pinyin"]):
                    note["Pinyin"] = pinyin_diacritic(note["Pinyin"])
                    fixed["pinyin"] += 1
                new_sent = (sents.get(w) or [""])[0]
                if new_sent:
                    marked = new_sent.replace(w, f"<b>{w}</b>", 1)
                    if note["SentenceSimplified"] != marked:
                        note["SentenceSimplified"] = marked
                        fixed["sentence"] += 1
                elif note["SentenceSimplified"]:
                    note["SentenceSimplified"] = ""
                    fixed["sentence_cleared"] += 1
                if counts.get(w) and note["CustomFreq"] != stars(counts[w]):
                    note["CustomFreq"] = stars(counts[w])
                    fixed["freq"] += 1
                col.update_note(note)
            print(f"refreshed {len(nids)} notes in {DECK}: " +
                  ", ".join(f"{k} {v}" for k, v in fixed.most_common()))
            if not a.apply:
                print("(dry run — nothing written)")
                return
            _sync(col)
            return

        # ---- what already exists, and where -------------------------------------
        card_of, seen_words, deck_of = {}, set(), {}
        for nid in col.find_notes(""):
            note = col.get_note(nid)
            d = dict(note.items())
            w = next((d[f].strip() for f in ("Simplified", "Chinese", "Front",
                                             "Target Word", "Word") if d.get(f, "").strip()), None)
            if not w:
                continue
            decks = set()
            for c in note.cards():
                decks.add(col.decks.name(c.did))
                if c.type != 0 or c.reps > 0:
                    seen_words.add(w)
                if c.ord == 0 and note.note_type()["name"] == NOTETYPE:
                    card_of[w] = c.id
            deck_of.setdefault(w, set()).update(decks)

        # ---- rank the book's words ----------------------------------------------
        gather, fresh = [], []
        for w, n in sorted(counts.items(), key=lambda x: -x[1]):
            if n < MIN_N or w not in ced or w in known or w in propers:
                continue
            if w not in deck_of:
                fresh.append((w, n))
            elif w in seen_words or deck_of[w] & set(PROTECTED):
                continue                                   # studied, or HSK's business
            elif all(x.startswith("Hidden::Archive") for x in deck_of[w]) and w in card_of:
                gather.append((w, n))
        pool = sorted(gather + fresh, key=lambda x: -x[1])

        if a.dump_pool:
            head = pool[:int(a.n * 1.6)]        # headroom for whatever screening drops
            psents = sample_sentences(text, [w for w, _ in head])
            Path(a.dump_pool).write_text(json.dumps(
                [{"word": w, "n": n, "pinyin": ced[w][1], "gloss": ced[w][2],
                  "sentences": psents.get(w, []),
                  "source": "archive" if w in card_of else "new"} for w, n in head],
                ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"pool of {len(head)} -> {a.dump_pool}")
            return

        drop = {}
        if Path(a.exclude).exists():
            drop = {d["word"]: d.get("reason", "") for d in
                    json.loads(Path(a.exclude).read_text())["drop"]}
            pool = [(w, n) for w, n in pool if w not in drop]

        picked = pool[:a.n]
        pickset = {w for w, _ in picked}
        sents = sample_sentences(text, sorted(pickset))

        print(f"deck: {DECK}   target {a.n}   selected {len(picked)}"
              + (f"   ({len(drop)} screened out)" if drop else "   (UNSCREENED)"))
        print(f"  {sum(1 for w,_ in picked if w in card_of)} archived cards to gather, "
              f"{sum(1 for w,_ in picked if w not in card_of)} new notes to create")
        print(f"  frequency range {picked[0][1]}× … {picked[-1][1]}× in the book")
        print("  " + " ".join(f"{w}" for w, _ in picked[:30]) + " …")

        # ---- safety: nothing selected may belong to a protected deck -------------
        bad = [w for w in pickset if deck_of.get(w, set()) & set(PROTECTED)]
        if bad:
            sys.exit(f"ABORT: {len(bad)} selected words have cards in {PROTECTED}: {bad[:10]}")
        hsk_before = {d: len(col.find_cards(f'deck:"{d}"')) for d in PROTECTED}
        hsk_unsusp_before = {d: len(col.find_cards(f'deck:"{d}" -is:suspended'))
                             for d in PROTECTED}

        if not a.apply:
            print("\n(dry run — nothing written; re-run through anki_op.sh with --apply)")
            return

        # ---- build ---------------------------------------------------------------
        did = col.decks.id(DECK)                       # creates if absent
        preset = next(c for c in col.decks.all_config() if c["name"] == PRESET)
        deck = col.decks.get(did)
        deck["conf"] = preset["id"]                    # reuse Mined's config, never a new one
        col.decks.save(deck)

        base = (col.db.scalar("select max(due) from cards where type=0 and due<1000000") or 0) + 1
        model = col.models.by_name(NOTETYPE)
        moved = created = 0

        for rank, (w, n) in enumerate(picked):
            sentence = sents.get(w, [])
            if w in card_of:                            # gather the archived card
                card = col.get_card(card_of[w])
                card.did = did
                card.queue = 0                          # new (unsuspended)
                card.type = 0
                card.due = base + rank
                col.update_card(card)
                note = card.note()
                moved += 1
            else:                                       # brand-new word
                trad, pinyin, gloss = ced[w]
                note = col.new_note(model)
                note["Simplified"] = w
                note["Traditional"] = trad
                note["Pinyin"] = pinyin_diacritic(pinyin)
                note["Meaning"] = gloss
                col.add_note(note, did)
                for c in note.cards():
                    if c.ord == 0:
                        c.due = base + rank
                        col.update_card(c)
                    else:
                        c.queue = -1                    # recognition only, like Mined
                        col.update_card(c)
                created += 1

            note["CustomFreq"] = stars(n)
            if sentence and not note["SentenceSimplified"]:
                note["SentenceSimplified"] = sentence[0].replace(w, f"<b>{w}</b>", 1)
            if hsk.get(w):
                note.add_tag(f"HSK::HSK{hsk[w]}")
            for t in TAGS:
                note.add_tag(t)
            col.update_note(note)

        # ---- verify ---------------------------------------------------------------
        for d in PROTECTED:
            after = len(col.find_cards(f'deck:"{d}"'))
            after_u = len(col.find_cards(f'deck:"{d}" -is:suspended'))
            assert after == hsk_before[d] and after_u == hsk_unsusp_before[d], \
                f"{d} changed: {hsk_before[d]}/{hsk_unsusp_before[d]} -> {after}/{after_u}"
            print(f"  {d}: {after} cards, {after_u} unsuspended — unchanged ✓")

        got = len(col.find_cards(f'deck:"{DECK}" -is:suspended'))
        conf = col.decks.config_dict_for_deck_id(did)
        print(f"\n{DECK}: {got} unsuspended cards "
              f"({moved} gathered from archive, {created} newly created)")
        print(f"  preset: {conf['name']} (new/day {conf['new']['perDay']}, "
              f"order {conf['new']['order']}, retention {conf.get('desiredRetention')})")
        assert conf["name"] == PRESET, "deck did not get the Mined preset"

        _sync(col)
    finally:
        col.close()


if __name__ == "__main__":
    main()
