"""Fill the Notes field with usage guidance on HSK cards that had none.

The gloss says what a word means; it does not say how to deploy it, which is the actual
difficulty for a heritage reader who can already read the characters. 作用 and 起作用 were
indistinguishable on their cards until one carried "noun, never a verb — something else
does the acting" and the other "verb phrase, 起 + 作用, so it splits".

Notes were written only where something is non-obvious — collocations, a grammatical
pattern, a near-synonym contrast, register, a trap. 1,134 of 2,240 candidates got one; the
rest are concrete nouns and transparent compounds where the gloss already suffices, and
padding those would be noise on every future review.

Scope is HSK 2-6, unsuspended, Notes empty. HSK 1 is excluded (too basic to need it) and
HSK 7-9 is left for later — it is 5,160 cards and far from current study.

Usage: bash freq_data/anki_op.sh usage-notes freq_data/apply_usage_notes.py --apply
"""
import argparse
import json
import re

from anki.collection import Collection
from opencc import OpenCC

ROOT = "/home/vincent/anki-headless"

# Card defects the note writers surfaced while reading these cards closely. Each is a card
# teaching the wrong thing, not a missing note: 法制 (legal system) was glossed "made in
# France"; 老婆's example shows 老婆婆, a different word; 著作 is a noun but its example uses
# it as a verb; 结实's example demonstrates jiē shí "bear fruit" while the headword is the
# jiēshi "sturdy" sense.
DEFECTS = {
    "法制": {"meaning": "legal system; rule of law",
             "sentence": "国家正在不断完善<b>法制</b>建设。",
             "pinyin": "Guójiā zhèngzài búduàn wánshàn fǎzhì jiànshè.",
             "english": "The country is continually improving its legal system."},
    "老婆": {"sentence": "他每天下班后都会给<b>老婆</b>打电话。",
             "pinyin": "Tā měitiān xiàbān hòu dōu huì gěi lǎopo dǎ diànhuà.",
             "english": "He calls his wife every day after work."},
    "著作": {"sentence": "这位学者的<b>著作</b>影响了很多人。",
             "pinyin": "Zhè wèi xuézhě de zhùzuò yǐngxiǎng le hěn duō rén.",
             "english": "This scholar's writings have influenced many people."},
    "结实": {"sentence": "这张桌子很<b>结实</b>，用了十年也没坏。",
             "pinyin": "Zhè zhāng zhuōzi hěn jiēshi, yòng le shí nián yě méi huài.",
             "english": "This table is sturdy — ten years of use and it still isn't broken."},
}


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    notes = json.load(open(f"{ROOT}/freq_data/hsk_usage_notes.json"))
    cc = OpenCC("s2tw")
    col = Collection(args.db)
    try:
        written = skipped = blank = 0
        for e in notes:
            note_text = (e.get("note") or "").strip()
            if not note_text:
                blank += 1
                continue
            try:
                note = col.get_note(e["nid"])
            except Exception:
                skipped += 1
                continue
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            if strip_html(note.fields[IX["Simplified"]]) != e["word"]:
                skipped += 1          # note changed under us; never write to the wrong card
                continue
            if strip_html(note.fields[IX["Notes"]]):
                skipped += 1          # gained a note since the export; don't overwrite
                continue
            note.fields[IX["Notes"]] = note_text
            if args.apply:
                col.update_note(note)
            written += 1

        print(f"usage notes: {written} written, {blank} deliberately blank, {skipped} skipped")

        fixed = []
        for word, d in DEFECTS.items():
            for nid, in col.db.all("SELECT id FROM notes WHERE sfld=?", word):
                note = col.get_note(nid)
                if note.note_type()["name"] != "ChineseVocabulary":
                    continue
                IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
                if "meaning" in d:
                    note.fields[IX["Meaning"]] = d["meaning"]
                simp = d["sentence"]
                note.fields[IX["SentenceSimplified"]] = simp
                note.fields[IX["SentenceTraditional"]] = cc.convert(simp)
                note.fields[IX["SentencePinyin"]] = d["pinyin"]
                note.fields[IX["SentenceMeaning"]] = d["english"]
                # keep any cloze front in step with the new back
                if strip_html(note.fields[IX["SentenceSimplifiedCloze"]]):
                    blanked = re.sub(r"<b>.*?</b>", "[ ]", simp)
                    note.fields[IX["SentenceSimplifiedCloze"]] = strip_html(blanked)
                    note.fields[IX["SentenceTraditionalCloze"]] = strip_html(cc.convert(blanked))
                note.fields[IX["SentenceAudio"]] = ""   # voiced the old sentence
                if args.apply:
                    col.update_note(note)
                fixed.append(word)
        print(f"defective cards repaired: {len(fixed)} ({', '.join(fixed)})")

        if args.apply:
            still = 0
            for e in notes:
                if not (e.get("note") or "").strip():
                    continue
                try:
                    n = col.get_note(e["nid"])
                except Exception:
                    continue
                IX = {f["name"]: i for i, f in enumerate(n.note_type()["flds"])}
                if not strip_html(n.fields[IX["Notes"]]):
                    still += 1
            print(f"\nverify: intended notes still empty: {still} (want 0)")
        else:
            print("\nDRY-RUN — nothing written.")
    finally:
        col.close()


if __name__ == "__main__":
    main()
