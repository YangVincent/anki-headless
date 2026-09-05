#!/usr/bin/env python3
"""Give the front-band 《黑暗森林》 nouns a real sentence from the book.

WHY. 40 book words were tagged `next::黑暗森林` on 2026-09-05 and now sit at the front of
the queue. 14 of them carry no sentence at all -- 舰队 was three fields deep: "fleet", no
Notes, no example. They are the concrete nouns you meet first, so they are the worst place
in the collection for a bare card. Each is tagged `needs::sentence`; this file answers
that tag for these 14 and drops it.

Every sentence is a VERBATIM line of 《黑暗森林》, checked against
freq_data/gen_santi/heianshenlin.jsonl at run time, not pasted on trust. A book sentence
beats an invented one here: these words only mean anything in the book's own setting, and
several teach a second front-band word for free (战舰 carries 水滴 and 恒星, 木星 carries
轨道 and 舰队).

Pinyin is authored, not generated. pypinyin lowercases 东方延绪 and 太阳系, and the deck's
own good examples ("Zài Zhōngguó, ...") capitalise proper nouns.

Usage: bash freq_data/anki_op.sh heian-add-sentences freq_data/heian_add_sentences.py --apply
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

# word -> (book sentence, authored pinyin, english)
SENTENCES = {
    "舰队": ("我要用球状闪电消灭地球舰队！",
             "Wǒ yào yòng qiúzhuàng shǎndiàn xiāomiè Dìqiú jiànduì!",
             "I will use ball lightning to destroy the Earth fleet!"),
    "战舰": ("在接下来的八秒钟内，水滴又穿透了十艘恒星级战舰。",
             "Zài jiēxiàlái de bā miǎozhōng nèi, shuǐdī yòu chuāntòu le shí sōu héngxīng jí zhànjiàn.",
             "In the next eight seconds the Droplet pierced ten more stellar-class battleships."),
    "舰长": ("两位副舰长都看着东方延绪。",
             "Liǎng wèi fù jiànzhǎng dōu kànzhe Dōngfāng Yánxù.",
             "Both deputy captains were looking at Dongfang Yanxu."),
    "恒星": ("我们在创造一颗虚拟的恒星！",
             "Wǒmen zài chuàngzào yì kē xūnǐ de héngxīng!",
             "We are creating a virtual star!"),
    "行星": ("你肯定知道它根本不可能观察到三体行星。",
             "Nǐ kěndìng zhīdào tā gēnběn bù kěnéng guānchá dào Sāntǐ xíngxīng.",
             "You surely know it cannot possibly observe the Trisolaran planet."),
    "木星": ("木星轨道上的舰队司令部时刻处于旋转状态，以产生人工重力。",
             "Mùxīng guǐdào shàng de jiànduì sīlìngbù shíkè chǔyú xuánzhuǎn zhuàngtài, "
             "yǐ chǎnshēng réngōng zhònglì.",
             "The fleet headquarters in Jupiter orbit rotates constantly, to produce artificial gravity."),
    "冬眠": ("据我所知，特遣队的家属都可以冬眠。",
             "Jù wǒ suǒ zhī, tèqiǎnduì de jiāshǔ dōu kěyǐ dōngmián.",
             "As far as I know, the families of the task force may all hibernate."),
    "核弹": ("我们从来就没有想到这些核弹的间距有什么意义。",
             "Wǒmen cónglái jiù méiyǒu xiǎngdào zhèxiē hédàn de jiānjù yǒu shénme yìyì.",
             "It never occurred to us that the spacing of these nuclear bombs meant anything."),
    "核聚变": ("稍后，核聚变的火焰才再次显示它的威力。",
              "Shāo hòu, héjùbiàn de huǒyàn cái zàicì xiǎnshì tā de wēilì.",
              "A little later the fusion flame showed its power again."),
    "量子": ("我要让他们变成量子幽灵去作战！",
             "Wǒ yào ràng tāmen biànchéng liàngzǐ yōulíng qù zuòzhàn!",
             "I will turn them into quantum ghosts to fight!"),
    "碎片": ("草坪上散落着纷乱的碎片，都是从巨树建筑上掉落下来的。",
             "Cǎopíng shàng sànluò zhe fēnluàn de suìpiàn, dōu shì cóng jùshù jiànzhù shàng "
             "diàoluò xiàlái de.",
             "Scattered fragments lay on the lawn, all fallen from the giant-tree buildings."),
    "悬浮": ("接着，他用左手抓住悬浮的瞄准镜，把它安装到手枪上。",
             "Jiēzhe, tā yòng zuǒshǒu zhuāzhù xuánfú de miáozhǔnjìng, bǎ tā ānzhuāng dào shǒuqiāng shàng.",
             "Then with his left hand he took the floating sight and fitted it to the pistol."),
    "队列": ("一分二十一秒后，第二队列的一百艘战舰也被全部摧毁。",
             "Yì fēn èrshíyī miǎo hòu, dì-èr duìliè de yìbǎi sōu zhànjiàn yě bèi quánbù cuīhuǐ.",
             "One minute and twenty-one seconds later, all hundred battleships of the second "
             "formation were destroyed too."),
    "失败主义": ("我们又要谈到失败主义了。",
                "Wǒmen yòu yào tán dào shībài zhǔyì le.",
                "We are going to talk about defeatism again."),
}

# 舰长 is the captain of a warship, not the rank "commander". The gloss came from a
# dictionary dump and reads as a rank, which is the one thing it is not.
MEANING_FIX = {"舰长": "captain (of a warship)"}


def strip_html(s):
    s = re.sub(r"\[sound:[^\]]*\]", "", s or "")
    return re.sub(r"<[^>]+>", "", s).replace("&nbsp;", " ").strip()


def bare(s):
    return re.sub(r"\s+", "", strip_html(s))


def is_split(word, sent):
    """A segmentation boundary falls INSIDE the word. See fix_split_sentences.py."""
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


def book_text():
    rows = [json.loads(l) for l in open(BOOK, encoding="utf-8") if l.strip()]
    return re.sub(r"[\s，。？！、“”：；…—·]", "", "".join(r["text"] for r in rows))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    cc = OpenCC("s2tw")
    text = book_text()
    col = Collection(args.db)
    try:
        seen_max = max(col.find_cards("") or [0])
        cards_before = col.card_count()

        print("── every sentence must be a verbatim book line, and must not split its word ──")
        for w, (sent, py, en) in SENTENCES.items():
            in_book = re.sub(r"[\s，。？！、“”：；…—·]", "", sent) in text
            split = is_split(w, sent)
            print(f"   {w:5s} in book: {in_book}   splits the word: {split}")
            assert in_book and not split and w in sent, w

        # resolve each word to its note through the collection, not a hardcoded nid
        targets = {}
        for nid in col.find_notes("tag:next::黑暗森林"):
            note = col.get_note(nid)
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            w = strip_html(note.fields[IX["Simplified"]])
            if w in SENTENCES:
                targets[w] = nid
        missing = set(SENTENCES) - set(targets)
        assert not missing, f"not in the front band: {missing}"
        print(f"\n{len(targets)} notes resolved from tag:next::黑暗森林")

        print("\n── writing ──")
        for w, nid in targets.items():
            sent, py, en = SENTENCES[w]
            note = col.get_note(nid)
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            assert bare(note.fields[IX["Pinyin"]]).lower() in bare(py).lower(), (w, py)
            simp = sent.replace(w, f"<b>{w}</b>", 1)
            note.fields[IX["SentenceSimplified"]] = simp
            note.fields[IX["SentenceTraditional"]] = cc.convert(simp)
            note.fields[IX["SentenceSimplifiedCloze"]] = sent.replace(w, "[ ]", 1)
            note.fields[IX["SentenceTraditionalCloze"]] = cc.convert(sent).replace(
                cc.convert(w), "[ ]", 1)
            note.fields[IX["SentencePinyin"]] = py
            note.fields[IX["SentenceMeaning"]] = en
            if w in MEANING_FIX:
                old = strip_html(note.fields[IX["Meaning"]])
                note.fields[IX["Meaning"]] = MEANING_FIX[w]
                print(f"   {w} Meaning: {old!r} -> {MEANING_FIX[w]!r}")
            note.remove_tag("needs::sentence")
            if args.apply:
                col.update_note(note)
            print(f"   {w:5s} {sent}\n   {'':5s} {py}")

        if not args.apply:
            print("\nDRY-RUN — nothing written.")
            return

        print("\n── verify ──")
        bad = []
        for w, nid in targets.items():
            note = col.get_note(nid)
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            s = bare(note.fields[IX["SentenceSimplified"]])
            if w not in s:
                bad.append((w, "word absent from sentence"))
            if is_split(w, s):
                bad.append((w, "word split by segmentation"))
            if bare(note.fields[IX["Pinyin"]]).lower() not in bare(
                    note.fields[IX["SentencePinyin"]]).lower():
                bad.append((w, "word pinyin absent"))
            if not bare(note.fields[IX["SentenceMeaning"]]):
                bad.append((w, "no translation"))
            if "[ ]" not in note.fields[IX["SentenceSimplifiedCloze"]]:
                bad.append((w, "cloze has no blank"))
            if "needs::sentence" in note.tags:
                bad.append((w, "still tagged needs::sentence"))
        print(f"  problems: {len(bad)} (want 0)")
        for w, why in bad:
            print(f"    {w}: {why}")

        left = [strip_html(col.get_note(n).fields[0])
                for n in col.find_notes("tag:next::黑暗森林 tag:needs::sentence")]
        print(f"  front-band notes still without a sentence: {len(left)} {left}")

        created = [cid for nid in targets.values() for cid in col.card_ids_of_note(nid)
                   if cid > seen_max]
        live = [cid for cid in created if col.get_card(cid).queue != -1]
        if live:
            col.sched.suspend_cards(live)
            print(f"  suspended {len(live)} generated card(s) to match the Cloze deck")
        still = [cid for cid in created if col.get_card(cid).queue != -1]
        print(f"  cards {cards_before} -> {col.card_count()} ({len(created)} generated, "
              f"{len(still)} left unsuspended, want 0)")
        assert not bad and not still and not left
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
