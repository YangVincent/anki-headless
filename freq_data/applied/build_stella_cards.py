#!/usr/bin/env python3
"""Build the Stella An deck's notes from the curated + filled JSON.

FIVE EXAMPLES WERE UNUSABLE and are handled here, not silently shipped. In each the word
appears ONLY inside a longer word, so the sentence teaches something else:
    同理  -> only ever 同理心. The WORD is changed to 同理心; teaching 同理 was wrong.
    概览  -> only 概览效应 (a fixed spaceflight term).      DROPPED.
    存在论 -> used ad hoc for "aliens exist", not ontology.  DROPPED.
    保护主义 -> only 动物保护主义者. Word kept, SENTENCE dropped.
    封禁  -> stands alone in 铁拳封禁女权. Kept as is.
Result is 78 notes, not 80. A padded 80 would be worse than an honest 78.

Run through freq_data/anki_op.sh. Dry-run by default; pass --apply to write.
"""
import argparse
import json
import re

from anki.collection import Collection

COL = "/home/vincent/anki-headless/collection.anki2"
GEN = "/home/vincent/anki-headless/freq_data/gen_mined"
DECK = "Stella An"
DROP = {"概览", "存在论"}
RENAME = {"同理": ("同理心", "tóng lǐ xīn", "empathy")}
NO_SENTENCE = {"保护主义"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    filled = {r["word"]: r for r in json.load(open(f"{GEN}/stella_cards_output.json"))}
    base = json.load(open(f"{GEN}/stella_cards_input.json"))

    col = Collection(COL)
    try:
        cv = col.models.by_name("ChineseVocabulary")
        F = {f["name"]: i for i, f in enumerate(cv["flds"])}
        did = col.decks.id_for_name(DECK)
        assert did, f"deck {DECK!r} does not exist"

        existing = {}
        for nid in col.models.nids(cv["id"]):
            existing.setdefault(col.get_note(nid).fields[F["Simplified"]].strip(), nid)

        plan, skipped, reuse = [], [], []
        for b in base:
            w = b["word"]
            if w in DROP:
                skipped.append((w, "example unusable, no alternative in her corpus")); continue
            f = filled.get(w, {})
            mean = f.get("meaning") or b["meaning"]
            sent = "" if w in NO_SENTENCE else (f.get("sentence") or "")
            spy = "" if w in NO_SENTENCE else (f.get("sent_pinyin") or "")
            sen = "" if w in NO_SENTENCE else (f.get("sent_english") or "")
            py, trad = b["pinyin"], b["traditional"]
            if w in RENAME:
                w, py, mean = RENAME[w]
                trad = w
            if w in existing:
                # 46 of the 80 already exist, ALL suspended (43 Archive, 3 non-HSK).
                # They passed the curation filter because that filter asked "is it LIVE",
                # not "does a note exist". Reuse them -- creating a second note is exactly
                # the duplicate problem that put 145 twins in this collection.
                reuse.append((w, existing[w], mean, sent, spy, sen)); continue
            if not mean:
                skipped.append((w, "no meaning")); continue
            if sent and w not in sent:
                skipped.append((w, "word absent from its own sentence")); continue
            plan.append((w, py, mean, trad, sent, spy, sen, b))

        print(f"to create: {len(plan)}   to reuse: {len(reuse)}   dropped: {len(skipped)}")
        for w, why in skipped:
            print(f"   skip {w}: {why}")
        if not args.apply:
            print("\nsample:")
            for w, py, mean, trad, sent, spy, sen, b in plan[:4]:
                print(f"   {w} [{py}] {mean}")
                print(f"      {sent[:60]}")
            print("\nDRY-RUN (pass --apply)")
            return

        moved = filled_n = 0
        for w, nid, mean, sent, spy, sen in reuse:
            n = col.get_note(nid)
            cids = [c.id for c in n.cards()]
            col.sched.unsuspend_cards(cids)
            col.set_deck([c.id for c in n.cards() if c.ord == 0], did)
            touched = False
            if sent and not re.sub(r"<[^>]+>", "", n.fields[F["SentenceSimplified"]]).strip():
                n.fields[F["SentenceSimplified"]] = sent.replace(w, f"<b>{w}</b>", 1)
                n.fields[F["SentencePinyin"]] = spy
                n.fields[F["SentenceMeaning"]] = sen
                touched = True
            if "stella-an" not in n.tags:
                n.tags.append("stella-an"); touched = True
            if touched:
                col.update_note(n); filled_n += 1
            moved += 1
        print(f"reused {moved} existing note(s); filled a sentence on {filled_n}")

        made = 0
        for w, py, mean, trad, sent, spy, sen, b in plan:
            n = col.new_note(cv)
            n.fields[F["Simplified"]] = w
            n.fields[F["Pinyin"]] = py
            n.fields[F["Meaning"]] = mean
            n.fields[F["Traditional"]] = trad
            n.fields[F["CustomFreq"]] = f"zipf {b['zipf']}"
            if sent:
                n.fields[F["SentenceSimplified"]] = sent.replace(w, f"<b>{w}</b>", 1)
                n.fields[F["SentencePinyin"]] = spy
                n.fields[F["SentenceMeaning"]] = sen
            n.tags = ["stella-an", f"topic::{b['domain']}"]
            col.add_note(n, did)
            made += 1

        print(f"\ncreated {made} note(s) in {DECK!r}")
        cards = col.db.scalar("SELECT count(*) FROM cards WHERE did=?", did)
        ord0 = col.db.scalar("SELECT count(*) FROM cards WHERE did=? AND ord=0", did)
        live = col.db.scalar(
            "SELECT count(*) FROM cards WHERE did=? AND ord=0 AND queue>=0", did)
        print(f"verify: {cards} card(s) in the deck, {ord0} forward, {live} unsuspended")
        assert ord0 == made + moved, (ord0, made, moved)
        assert live == ord0, "some forward card is still suspended"
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
