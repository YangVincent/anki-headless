#!/usr/bin/env python3
"""Replace example sentences that never contain their own target word.

THE DEFECT. 不要紧 carried the sentence 不要紧张，放松、放松！ That string holds the
characters 不要紧, but it parses as 不要 + 紧张 "do not be nervous". The word is not in
it. The card's stored SentencePinyin said so out loud -- "Bù yào jǐnzhāng" -- and its
cloze read "[ ]张，放松、放松！", a blank followed by an orphan 张.

HOW THE SET WAS FOUND, and why the obvious rule is wrong. Segment the sentence with
jieba and locate the word's character span. Flagging every word that is not its own
token returns 1694 cards in Main, and nearly all are fine: jieba merely glued the word
into a longer compound (谢谢 inside 谢谢您, 北京 inside 北京市). The word is still there.
The real rule needs a boundary INSIDE the word:
    the span covers 2+ tokens, AND a token crosses the span's edge.
That returns 49. Reading all 49 by hand gave 12 real defects; the rest are jieba errors
where the sentence is correct (皮带/皮带来搭, 三明治/火腿三明治, 金子/纯金子 -- that last
one is named as a known jieba bug in fix_sentence_pinyin.py's own docstring). So the
checker FLAGS, and a human picks. This file carries the 11 that were picked; 不要紧, the
twelfth, was fixed in heian_sentences.py.

Every replacement sentence is re-checked by the same rule before it is written. Four of
the first drafts failed it and were replaced. 要不 fails the naive token test in every
context jieba knows, but passes the real rule (要/不 tile the word exactly), so it stays.

Usage: bash freq_data/anki_op.sh split-sentences freq_data/fix_split_sentences.py --apply
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import jieba
from anki.collection import Collection
from opencc import OpenCC

ROOT = "/home/vincent/anki-headless"

# nid -> (word, sentence, pinyin, english). Pinyin is authored, not generated: pypinyin
# lowercases proper nouns and spaces quotes away from their clause, and the deck's own
# good examples ("Zài Zhōngguó, ...", "“Zhànzhù!”") do neither.
SENTENCES = {
    1537328243735: ("片面", "你这样看问题太片面了。",
                    "Nǐ zhèyàng kàn wèntí tài piànmiàn le.",
                    "You are looking at the problem far too one-sidedly."),
    1537328243885: ("天真", "你别那么天真。",
                    "Nǐ bié nàme tiānzhēn.",
                    "Don't be so naive."),
    1537328245134: ("要不", "我们走吧，要不就晚了。",
                    "Wǒmen zǒu ba, yàobù jiù wǎn le.",
                    "Let's go, or else we will be late."),
    1537328245798: ("表演", "孩子们在台上表演节目。",
                    "Háizimen zài tái shàng biǎoyǎn jiémù.",
                    "The children are performing a show on the stage."),
    1393817668686: ("创作", "他花了三年创作这部小说。",
                    "Tā huā le sān nián chuàngzuò zhè bù xiǎoshuō.",
                    "He spent three years writing this novel."),
    1393817668927: ("着手", "我们下周着手准备这个项目。",
                    "Wǒmen xià zhōu zhuóshǒu zhǔnbèi zhège xiàngmù.",
                    "We start preparing this project next week."),
    1393817669010: ("是非", "这件事的是非很清楚。",
                    "Zhè jiàn shì de shìfēi hěn qīngchu.",
                    "The rights and wrongs of this matter are clear."),
    1393817669902: ("上游", "这条河的上游有一座水库。",
                    "Zhè tiáo hé de shàngyóu yǒu yí zuò shuǐkù.",
                    "There is a reservoir on the upper reaches of this river."),
    1393817670309: ("心得", "他分享了自己的心得。",
                    "Tā fēnxiǎng le zìjǐ de xīndé.",
                    "He shared what he had learned."),
    1783527789194: ("擦干", "她用毛巾把头发擦干了。",
                    "Tā yòng máojīn bǎ tóufa cāgān le.",
                    "She dried her hair with a towel."),
    # 年前 is only a word in the "before Chinese New Year" sense. The old 十年前 is
    # 十年 + 前, so no sentence of that shape can teach it.
    1708747484188: ("年前", "年前我们要把房子打扫干净。",
                    "Niánqián wǒmen yào bǎ fángzi dǎsǎo gānjìng.",
                    "Before the New Year we must clean the house."),
}


def strip_html(s):
    s = re.sub(r"\[sound:[^\]]*\]", "", s or "")
    return re.sub(r"<[^>]+>", "", s).replace("&nbsp;", " ").strip()


def bare(s):
    return re.sub(r"\s+", "", strip_html(s))


def is_split(word, sent):
    """True when a segmentation boundary falls INSIDE the word.

    Not 'the word is not a token' -- that flags 1694 cards and is almost always jieba
    gluing the word to a neighbour. The word must be torn: covered by 2+ tokens, with a
    token reaching past its edge."""
    if not word or not sent or word not in sent:
        return False
    pos, spans = 0, []
    for t in jieba.cut(sent):
        spans.append((pos, pos + len(t))); pos += len(t)
    i = sent.index(word); j = i + len(word)
    cover = [(a, b) for a, b in spans if a < j and b > i]
    if len(cover) < 2:
        return False
    if cover[0][0] == i and cover[-1][1] == j:   # the word is tiled by whole tokens
        return False
    return cover[0][0] < i or cover[-1][1] > j


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    cc = OpenCC("s2tw")     # s2t picks 喫/爲/裏, which this deck does not use
    col = Collection(args.db)
    try:
        cards_before = col.card_count()
        seen_max = max(col.find_cards("") or [0])

        # every replacement must survive the same rule that condemned the old one
        print("── replacements checked by the same rule ──")
        for nid, (word, sent, py, _) in SENTENCES.items():
            assert word in sent, (nid, word)
            assert not is_split(word, sent), (nid, word, sent)
            print(f"   {word:4s} OK  {sent}")

        print("\n── rewriting ──")
        for nid, (word, sent, py, en) in SENTENCES.items():
            note = col.get_note(nid)
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            have = strip_html(note.fields[IX["Simplified"]])
            assert have == word, (nid, have, word)
            assert bare(note.fields[IX["Pinyin"]]).lower() in bare(py).lower(), (nid, py)
            old = strip_html(note.fields[IX["SentenceSimplified"]])

            simp = sent.replace(word, f"<b>{word}</b>", 1)
            note.fields[IX["SentenceSimplified"]] = simp
            note.fields[IX["SentenceTraditional"]] = cc.convert(simp)
            note.fields[IX["SentenceSimplifiedCloze"]] = sent.replace(word, "[ ]", 1)
            note.fields[IX["SentenceTraditionalCloze"]] = cc.convert(sent).replace(
                cc.convert(word), "[ ]", 1)
            note.fields[IX["SentencePinyin"]] = py
            note.fields[IX["SentenceMeaning"]] = en
            # the old sentence's audio reads the old sentence out loud
            if "SentenceAudio" in IX:
                note.fields[IX["SentenceAudio"]] = ""
            if args.apply:
                col.update_note(note)
            print(f"   {word:4s} - {old}\n   {'':4s} + {sent}   {py}")

        if not args.apply:
            print("\nDRY-RUN — nothing written.")
            return

        print("\n── verify ──")
        bad = []
        for nid, (word, sent, py, en) in SENTENCES.items():
            note = col.get_note(nid)
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            s = bare(note.fields[IX["SentenceSimplified"]])
            if word not in s:
                bad.append((word, "word absent"))
            if is_split(word, s):
                bad.append((word, "still split"))
            if bare(note.fields[IX["Pinyin"]]).lower() not in bare(
                    note.fields[IX["SentencePinyin"]]).lower():
                bad.append((word, "word pinyin absent from sentence pinyin"))
            if not bare(note.fields[IX["SentenceMeaning"]]):
                bad.append((word, "no meaning"))
            if "[ ]" not in note.fields[IX["SentenceSimplifiedCloze"]]:
                bad.append((word, "cloze has no blank"))
            if bare(note.fields[IX["SentenceAudio"]]) if "SentenceAudio" in IX else False:
                bad.append((word, "stale sentence audio"))
        print(f"  problems: {len(bad)} (want 0)")
        for w, why in bad:
            print(f"    {w}: {why}")

        # Writing a cloze field makes Anki generate a Cloze card for a note that had
        # none. The Cloze deck is suspended in full -- 8456 of 8458 cards -- so a live
        # new card there would push a card into study that was never asked for. Suspend
        # what this script generates rather than only asserting about it: the first run
        # generated two, and one of them (要不) came out queue=0.
        created = [cid for nid in SENTENCES for cid in col.card_ids_of_note(nid)
                   if cid > seen_max]
        live = [cid for cid in created if col.get_card(cid).queue != -1]
        if live:
            col.sched.suspend_cards(live)
            print(f"  suspended {len(live)} generated card(s) to match the Cloze deck")
        still = [cid for cid in created if col.get_card(cid).queue != -1]
        print(f"  cards {cards_before} -> {col.card_count()} ({len(created)} generated)")
        print(f"  generated cards left unsuspended: {len(still)} (want 0)")
        assert not bad and not still
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
