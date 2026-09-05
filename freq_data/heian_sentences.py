#!/usr/bin/env python3
"""Repair the sentence fields of the 《黑暗森林》 mined notes, plus two bad examples.

WHY. A scan of the 407 notes tagged 黑暗森林 found two defects that exist nowhere else in
the Main deck: 121 notes carry no sentence at all, and 20 carry a sentence with no pinyin
and no meaning. Reading the 20 showed the sentences came from two different sources. Four
are real book lines. The rest are fragments from an anime subtitle corpus (小樱, 鸣人,
木叶, 忍术) or chapter-title lines from the table of contents, and they teach nothing.

WHAT IT DOES, in four groups:
  CLEAR  - 16 fragment sentences are removed and the note is tagged needs::sentence.
  FILL   - 4 real book lines get pinyin, a translation, traditional and cloze fields.
  TAG    - 29 sentence-less notes that lacked needs::sentence get it, so all 121 are
           one queue rather than two.
  WRITE  - 2 notes get an authored sentence: 水滴, whose fragment is replaced by the
           book's own naming line, and 不要紧, whose example 不要紧张 parses as
           不要 + 紧张 and never contained the word at all.

Sentence provenance was checked against freq_data/gen_santi/heianshenlin.jsonl, not
assumed: 破壁, 水星, 卢浮宫 and the new 水滴 line are present in the book text; the
cleared fragments are not.

Usage: bash freq_data/anki_op.sh heian-sentences freq_data/heian_sentences.py --apply
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from anki.collection import Collection
from opencc import OpenCC

ROOT = "/home/vincent/anki-headless"
BOOK = f"{ROOT}/freq_data/gen_santi/heianshenlin.jsonl"

# Sentences that only lacked pinyin and a translation. nid -> (sentence, english).
# The first three are verified lines of 《黑暗森林》. The fourth is not from this book --
# 盖雷·唐纳利 does not appear in it -- but it is a complete, grammatical sentence that
# teaches 次声波, so it is kept and filled rather than thrown away. NOT_IN_BOOK records
# that, so the provenance check below stays honest instead of being loosened for all.
FILL = {
    1708747486220: ("这个人的真名一直不为人知，后来他被称为破壁人二号。",
                    "Zhège rén de zhēnmíng yìzhí bùwéirénzhī, hòulái tā bèi chēngwéi Pòbì Rén èr hào.",
                    "This man's real name was never known; later he was called Wallbreaker No. 2."),
    1708747487393: ("“我决定在水星进行试验。”雷迪亚兹说。",
                    "“Wǒ juédìng zài Shuǐxīng jìnxíng shìyàn.” Léi Díyàzī shuō.",
                    "“I have decided to run the test on Mercury,” Rey Diaz said."),
    1708747490604: ("“那，罗老师，你能带我去卢浮宫吗？”",
                    "“Nà, Luó lǎoshī, nǐ néng dài wǒ qù Lúfúgōng ma?”",
                    "“Then, Teacher Luo, can you take me to the Louvre?”"),
    1708747492790: ("“你是指音频，次声波，或者超声波？”盖雷·唐纳利问道。",
                    "“Nǐ shì zhǐ yīnpín, cìshēngbō, huòzhě chāoshēngbō?” Gàiléi·Tángnàlì wèndào.",
                    "“Do you mean audio frequency, infrasound, or ultrasound?” Garry Donnelly asked."),
}
NOT_IN_BOOK = {1708747492790}    # 次声波: good sentence, different source

# Authored replacements. nid -> (sentence, english, new Meaning or None, new Notes or None).
WRITE = {
    # The book's own naming line. It says why the probe is called 水滴, which is the
    # sense a reader of this book meets first.
    1708747484260: ("于是，人们给探测器换了个称呼，形象地叫它“水滴”。",
                    "Yúshì, rénmen gěi tàncèqì huàn le ge chēnghu, xíngxiàng de jiào tā “shuǐdī”.",
                    "So people gave the probe a new name, vividly calling it the “Droplet”.",
                    "water drop; droplet",
                    "Literally one drop of water. In 《黑暗森林》 it is the nickname for the "
                    "Trisolaran probe, taken from its shape and mirror finish."),
    # 不要紧张 is 不要 + 紧张 'do not be nervous'. The old note explained the mismatch
    # instead of fixing it; the sentence is replaced and the explanation deleted.
    1537328247134: ("你别担心，这点小伤不要紧。",
                    "Nǐ bié dānxīn, zhè diǎn xiǎo shāng bú yàojǐn.",
                    "Don't worry, this little cut is nothing serious.",
                    None, None),
}

SENT_FIELDS = ["SentenceSimplified", "SentenceTraditional", "SentenceSimplifiedCloze",
               "SentenceTraditionalCloze", "SentencePinyin", "SentenceMeaning",
               "SentenceAudio"]


def strip_html(s):
    s = re.sub(r"\[sound:[^\]]*\]", "", s or "")
    return re.sub(r"<[^>]+>", "", s).replace("&nbsp;", " ").strip()


def bare(s):
    return re.sub(r"\s+", "", strip_html(s))


def book_text():
    rows = [json.loads(l) for l in open(BOOK, encoding="utf-8") if l.strip()]
    return re.sub(r"[\s，。？！、“”：；…—·]", "", "".join(r["text"] for r in rows))


def scan(col):
    """Derive the three groups from the collection, not from a hardcoded list."""
    clear, tag = [], []
    for nid in col.find_notes("tag:*黑暗森林*"):
        note = col.get_note(nid)
        IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
        if "SentenceSimplified" not in IX:
            continue
        s = bare(note.fields[IX["SentenceSimplified"]])
        if not s:
            if "needs::sentence" not in note.tags:
                tag.append(nid)
        elif s[-1] not in "。！？…”\"'.!?" and nid not in WRITE:
            clear.append(nid)
    return clear, tag


def apply_sentence(note, IX, word, sent, py, english, cc):
    """Write the six sentence fields in the deck's own format."""
    simp = sent.replace(word, f"<b>{word}</b>", 1)
    note.fields[IX["SentenceSimplified"]] = simp
    note.fields[IX["SentenceTraditional"]] = cc.convert(simp)
    note.fields[IX["SentenceSimplifiedCloze"]] = sent.replace(word, "[ ]", 1)
    note.fields[IX["SentenceTraditionalCloze"]] = cc.convert(sent).replace(
        cc.convert(word), "[ ]", 1)
    note.fields[IX["SentencePinyin"]] = py
    note.fields[IX["SentenceMeaning"]] = english


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    cc = OpenCC("s2tw")          # s2t picks 喫/爲/裏, which this deck does not use
    text = book_text()
    col = Collection(args.db)
    try:
        cards_before = col.card_count()
        cards_seen_max = max(col.find_cards("") or [0])
        clear, tag = scan(col)
        print(f"scan: {len(clear)} fragments to clear, {len(tag)} to tag, "
              f"{len(FILL)} to fill, {len(WRITE)} to rewrite")

        # provenance: every sentence this script WRITES must be in the book, except the
        # authored 不要紧 line, which is a plain example and never claimed to be.
        for nid, (sent, _, _) in FILL.items():
            ok = re.sub(r"[\s，。？！、“”：；…—·]", "", sent) in text
            expect = nid not in NOT_IN_BOOK
            print(f"   provenance FILL  {nid} in book: {ok} (expected {expect})")
            assert ok == expect, nid
        for nid, (sent, _, _, _, _) in WRITE.items():
            if nid == 1708747484260:
                ok = re.sub(r"[\s，。？！、“”：；…—·]", "", sent) in text
                print(f"   provenance WRITE {nid} in book: {ok}")
                assert ok, nid

        # --- CLEAR ---
        for nid in clear:
            note = col.get_note(nid)
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            for name in SENT_FIELDS:
                if name in IX:
                    note.fields[IX[name]] = ""
            note.add_tag("needs::sentence")
            if args.apply:
                col.update_note(note)

        # --- TAG ---
        for nid in tag:
            note = col.get_note(nid)
            note.add_tag("needs::sentence")
            if args.apply:
                col.update_note(note)

        # --- FILL and WRITE ---
        touched = []
        for nid, (sent, py, english) in FILL.items():
            note = col.get_note(nid)
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            word = strip_html(note.fields[IX["Simplified"]])
            assert word in sent, (nid, word)
            assert bare(note.fields[IX["Pinyin"]]).lower() in bare(py).lower(), (nid, py)
            apply_sentence(note, IX, word, sent, py, english, cc)
            if args.apply:
                col.update_note(note)
            touched.append((word, sent, note.fields[IX["SentencePinyin"]]))

        for nid, (sent, py, english, meaning, notes) in WRITE.items():
            note = col.get_note(nid)
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            word = strip_html(note.fields[IX["Simplified"]])
            assert word in sent, (nid, word)
            assert bare(note.fields[IX["Pinyin"]]).lower() in bare(py).lower(), (nid, py)
            apply_sentence(note, IX, word, sent, py, english, cc)
            if meaning is not None:
                note.fields[IX["Meaning"]] = meaning
            if notes is not None:
                note.fields[IX["Notes"]] = notes
            if nid == 1537328247134:
                # delete the caption that explained the broken example away
                old = note.fields[IX["Notes"]]
                new = re.sub(r"\s*Watch the parse[^.]*\.\s*", " ", old).strip()
                note.fields[IX["Notes"]] = new
                print(f"\n   不要紧 Notes: {'caption removed' if new != old else 'NO CHANGE'}")
            if args.apply:
                col.update_note(note)
            touched.append((word, sent, note.fields[IX["SentencePinyin"]]))

        print()
        for w, s, p in touched:
            print(f"  {w:6} {s}\n  {'':6} {p}")

        if not args.apply:
            print("\nDRY-RUN — nothing written.")
            return

        # ---------- verify, in the same stopped-bot window ----------
        print("\n── verify ──")
        bad = []
        for nid in clear:
            note = col.get_note(nid)
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            if bare(note.fields[IX["SentenceSimplified"]]):
                bad.append((nid, "sentence not cleared"))
            if "needs::sentence" not in note.tags:
                bad.append((nid, "tag missing after clear"))
        for nid in tag:
            if "needs::sentence" not in col.get_note(nid).tags:
                bad.append((nid, "tag missing"))
        for nid in list(FILL) + list(WRITE):
            note = col.get_note(nid)
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            word = strip_html(note.fields[IX["Simplified"]])
            sp = bare(note.fields[IX["SentencePinyin"]]).lower()
            wp = bare(note.fields[IX["Pinyin"]]).lower()
            if not bare(note.fields[IX["SentenceMeaning"]]):
                bad.append((nid, "no SentenceMeaning"))
            if wp not in sp:
                bad.append((nid, f"word pinyin absent from sentence pinyin: {sp}"))
            if word not in bare(note.fields[IX["SentenceSimplified"]]):
                bad.append((nid, "word absent from sentence"))
            if "[ ]" not in note.fields[IX["SentenceSimplifiedCloze"]]:
                bad.append((nid, "cloze has no blank"))
        print(f"  problems: {len(bad)} (want 0)")
        for nid, why in bad:
            print(f"    {nid}: {why}")

        left = 0
        for nid in col.find_notes("tag:*黑暗森林*"):
            note = col.get_note(nid)
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            if "SentenceSimplified" not in IX:
                continue
            s = bare(note.fields[IX["SentenceSimplified"]])
            if s and (not bare(note.fields[IX["SentencePinyin"]])
                      or not bare(note.fields[IX["SentenceMeaning"]])):
                left += 1
        print(f"  黑暗森林 notes still having a sentence with no pinyin/meaning: {left} (want 0)")

        untagged = sum(1 for nid in col.find_notes("tag:*黑暗森林*")
                       if not bare(col.get_note(nid).fields[
                           {f["name"]: i for i, f in
                            enumerate(col.get_note(nid).note_type()["flds"])}
                           .get("SentenceSimplified", 0)])
                       and "needs::sentence" not in col.get_note(nid).tags)
        print(f"  sentence-less 黑暗森林 notes without needs::sentence: {untagged} (want 0)")

        # Filling a cloze field legitimately generates a Cloze card for notes that had
        # none. That is correct, not a defect -- but a NEW unsuspended cloze card would
        # push cards the user never asked for into the queue. So the rule is: cards may
        # be created, and every created card must be suspended, like its 245 siblings.
        cards_after = col.card_count()
        created = [cid for nid in list(FILL) + list(WRITE)
                   for cid in col.card_ids_of_note(nid)
                   if cid > cards_seen_max]
        live = [cid for cid in created if col.get_card(cid).queue != -1]
        print(f"  cards {cards_before} -> {cards_after} "
              f"({len(created)} generated by the new cloze fields)")
        print(f"  generated cards left unsuspended: {len(live)} (want 0)")
        assert not bad and left == 0 and untagged == 0 and not live
        assert cards_after - cards_before == len(created), (cards_after, cards_before, created)
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
