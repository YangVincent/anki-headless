#!/usr/bin/env python3
"""Give every remaining 《黑暗森林》 note a sentence, and drop `needs::sentence`.

WHY. 137 notes in the book set carried no example at all -- 舰队 was "fleet", no Notes, no
sentence. 14 were fixed when they reached the front band (heian_add_sentences.py); this
file does the other 123.

WHY THE SELECTION IS NOT AUTOMATIC. Picking a book line by string match produces wrong
cards, and three showed exactly how:
  火星  glossed "Mars", but the book's line means SPARKS -- same characters, same pinyin.
  身后  glossed "the time after one's death", but the line means "behind her".
  一号  glossed "first day of the month", but the line means "Base No. 1".
No segmentation rule catches that; the sentence has to be read against the card's own
gloss. So a script chose the candidates and a human chose among them, one at a time.

Two more automatic traps that the candidate pass DID have to fix:
  - an orphan quote from the neighbouring sentence ("”史晓明含泪把烟头...") -- 12 of them;
  - one line silently assigned to two different cards -- 左手 and 悬浮 both got the pistol
    sentence, 联席会议 and 轮值 both got the chair sentence. Sentences are now unique
    across the batch AND against every sentence already in the collection.

64 sentences are verbatim book lines, checked against heianshenlin.jsonl at run time.
59 are authored, because the book had no line under 26 characters that used the word in
the card's sense. The `book`/`authored` flag in the data file records which is which, and
the check below asserts the flag rather than trusting it.

Pinyin is authored throughout. The generator lowercases every name (dīngyí, luójí,
zhāng běihǎi), reads 泰勒 as "tàilēi", and spaces quotes away from their clause.

Usage: bash freq_data/anki_op.sh heian-fill freq_data/heian_fill_sentences.py --apply
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import jieba
from anki.collection import Collection
from opencc import OpenCC

ROOT = "/home/vincent/anki-headless"
BOOK = f"{ROOT}/freq_data/gen_santi/heianshenlin.jsonl"
DATA = [f"{ROOT}/freq_data/gen_heian/batch1.json", f"{ROOT}/freq_data/gen_heian/batch2.json"]


def strip_html(s):
    s = re.sub(r"\[sound:[^\]]*\]", "", s or "")
    return re.sub(r"<[^>]+>", "", s).replace("&nbsp;", " ").strip()


def bare(s):
    return re.sub(r"\s+", "", strip_html(s))


def pykey(s):
    """Pinyin compared without spaces or the syllable-separator apostrophe.

    The card's Pinyin field writes 尘埃 as "chén āi" and 法案 as "fǎ àn"; correct sentence
    pinyin needs the separator -- chén'āi, fǎ'àn -- or the syllables run together. The
    apostrophe is right, so the comparison drops it rather than the pinyin dropping it."""
    return re.sub(r"['’]", "", bare(s)).lower()


def norm(s):
    return re.sub(r"[\s，。？！、“”‘’：；…—·]", "", s)


def is_split(word, sent):
    if not word or not sent or word not in sent:
        return False
    pos, spans = 0, []
    for t in jieba.cut(sent):
        spans.append((pos, pos + len(t))); pos += len(t)
    i = sent.index(word); j = i + len(word)
    cover = [(a, b) for a, b in spans if a < j and b > i]
    if len(cover) < 2:
        return False
    if cover[0][0] == i and cover[-1][1] == j:
        return False
    return cover[0][0] < i or cover[-1][1] > j


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    data = {}
    for p in DATA:
        for k, v in json.load(open(p, encoding="utf-8")).items():
            assert k not in data, f"duplicate word across batches: {k}"
            data[k] = v
    rows = [json.loads(l) for l in open(BOOK, encoding="utf-8") if l.strip()]
    text = norm("".join(r["text"] for r in rows))
    cc = OpenCC("s2tw")
    col = Collection(args.db)
    try:
        seen_max = max(col.find_cards("") or [0])
        cards_before = col.card_count()

        # sentences already used anywhere -> a new one must not collide
        inuse = {}
        for nid in col.find_notes(""):
            note = col.get_note(nid)
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            if "SentenceSimplified" in IX:
                s = bare(note.fields[IX["SentenceSimplified"]])
                if s:
                    inuse.setdefault(s, nid)

        targets = {}
        for nid in col.find_notes("tag:*黑暗森林* tag:needs::sentence"):
            note = col.get_note(nid)
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            w = strip_html(note.fields[IX["Simplified"]])
            if w in data:
                targets[w] = nid
        missing = set(data) - set(targets)
        extra = {strip_html(col.get_note(n).fields[0])
                 for n in col.find_notes("tag:*黑暗森林* tag:needs::sentence")} - set(data)
        print(f"data rows {len(data)} | resolved {len(targets)} | "
              f"in data but not tagged: {sorted(missing)} | tagged but no data: {sorted(extra)}")
        assert not missing and not extra

        print("\n── checks ──")
        bad = []
        seen_sent = {}
        for w, (sent, py, en, src) in data.items():
            if w not in sent:
                bad.append((w, "word not in its own sentence"))
            if is_split(w, sent):
                bad.append((w, "segmentation splits the word"))
            if src == "book" and norm(sent) not in text:
                bad.append((w, "flagged book but NOT in the book"))
            if src == "authored" and norm(sent) in text:
                bad.append((w, "flagged authored but IS a book line"))
            if sent in seen_sent:
                bad.append((w, f"same sentence as {seen_sent[sent]}"))
            seen_sent[sent] = w
            if bare(sent) in inuse and inuse[bare(sent)] != targets[w]:
                bad.append((w, "sentence already used by another note"))
            note = col.get_note(targets[w])
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            wp = pykey(note.fields[IX["Pinyin"]])
            if wp and wp not in pykey(py):
                bad.append((w, f"card pinyin {wp!r} absent from {py!r}"))
        print(f"  problems before writing: {len(bad)} (want 0)")
        for w, why in bad:
            print(f"    {w}: {why}")
        assert not bad

        nb = sum(1 for v in data.values() if v[3] == "book")
        print(f"  {nb} verbatim book lines, {len(data) - nb} authored")

        for w, nid in targets.items():
            sent, py, en, src = data[w]
            note = col.get_note(nid)
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            simp = sent.replace(w, f"<b>{w}</b>", 1)
            note.fields[IX["SentenceSimplified"]] = simp
            note.fields[IX["SentenceTraditional"]] = cc.convert(simp)
            note.fields[IX["SentenceSimplifiedCloze"]] = sent.replace(w, "[ ]", 1)
            note.fields[IX["SentenceTraditionalCloze"]] = cc.convert(sent).replace(
                cc.convert(w), "[ ]", 1)
            note.fields[IX["SentencePinyin"]] = py
            note.fields[IX["SentenceMeaning"]] = en
            note.remove_tag("needs::sentence")
            if args.apply:
                col.update_note(note)

        if not args.apply:
            print("\nDRY-RUN — nothing written.")
            return

        print("\n── verify ──")
        bad = []
        for w, nid in targets.items():
            note = col.get_note(nid)
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            s = bare(note.fields[IX["SentenceSimplified"]])
            if w not in s or is_split(w, s):
                bad.append((w, "word absent or split"))
            if not bare(note.fields[IX["SentenceMeaning"]]):
                bad.append((w, "no translation"))
            if "[ ]" not in note.fields[IX["SentenceSimplifiedCloze"]]:
                bad.append((w, "cloze has no blank"))
            if "needs::sentence" in note.tags:
                bad.append((w, "tag not removed"))
        print(f"  problems: {len(bad)} (want 0)")
        for w, why in bad:
            print(f"    {w}: {why}")

        left = col.find_notes("tag:*黑暗森林* tag:needs::sentence")
        print(f"  黑暗森林 notes still tagged needs::sentence: {len(left)} (want 0)")
        nosent = 0
        for nid in col.find_notes("tag:*黑暗森林*"):
            note = col.get_note(nid)
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            if "SentenceSimplified" in IX and not bare(note.fields[IX["SentenceSimplified"]]):
                nosent += 1
        print(f"  黑暗森林 notes with no sentence at all: {nosent} (want 0)")

        created = [cid for nid in targets.values() for cid in col.card_ids_of_note(nid)
                   if cid > seen_max]
        live = [cid for cid in created if col.get_card(cid).queue != -1]
        if live:
            col.sched.suspend_cards(live)
            print(f"  suspended {len(live)} generated card(s) to match the Cloze deck")
        still = [cid for cid in created if col.get_card(cid).queue != -1]
        print(f"  cards {cards_before} -> {col.card_count()} ({len(created)} generated, "
              f"{len(still)} unsuspended, want 0)")
        assert not bad and not still and not left and nosent == 0
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
