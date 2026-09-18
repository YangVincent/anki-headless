#!/usr/bin/env python3
"""Create the 以 A 为 B ending cards, and promote the three that already sit in Archive.

The frame 以 A 为 B takes a bound word in the B slot. Vincent held a card for the noun in
the A slot but not for the ending itself, so the ending was never the subject of a card.
One card per ending, headword `为X`, plus the three four-character idioms whose A slot is
fixed (以退为进 / 以攻为守 / 以邻为壑).

Usage: bash freq_data/anki_op.sh yiwei-cards freq_data/yiwei_cards.py --apply
       (no --apply prints every card and writes nothing)
"""
import sys, argparse, re

sys.path.insert(0, "/home/vincent/anki-headless")
from anki.collection import Collection
import decks as deck_registry

COL = "/home/vincent/anki-headless/collection.anki2"
NOTETYPE = "ChineseVocabulary"
TAGS = ["claude", "chinese", "grammar::以A为B", "next::以A为B"]

# simplified, traditional, pinyin, meaning, part-of-speech, notes,
# sentence, sentence-traditional, sentence-pinyin, sentence-meaning
CARDS = [
 ("为例", "為例", "wéi lì", "to take as an example; used only in 以…为例", "verb",
  "以…为例 = take … as an example. Also 以此为例. The A slot is the thing you hold up: 以北京为例 · 以这家公司为例.",
  "以北京为例，房价十年翻了一倍。", "以北京為例，房價十年翻了一倍。",
  "Yǐ Běijīng wéi lì, fángjià shí nián fān le yí bèi.",
  "Take Beijing as an example: house prices doubled in ten years."),
 ("为本", "為本", "wéi běn", "to treat as the foundation", "verb",
  "以…为本 = treat … as the foundation. Set phrase 以人为本 people-oriented. Also 以诚信为本 · 以农为本.",
  "这家公司以诚信为本。", "這家公司以誠信為本。",
  "Zhè jiā gōngsī yǐ chéngxìn wéi běn.",
  "This company treats integrity as its foundation."),
 ("为纲", "為綱", "wéi gāng", "to take as the guiding principle", "verb",
  "以…为纲 = take … as the guiding principle. 纲 is the main rope of a net. Political register: 以阶级斗争为纲 · 以粮为纲.",
  "那个年代以阶级斗争为纲。", "那個年代以階級鬥爭為綱。",
  "Nàge niándài yǐ jiējí dòuzhēng wéi gāng.",
  "That era took class struggle as its guiding principle."),
 ("为生", "為生", "wéi shēng", "to make a living by", "verb",
  "以…为生 = make a living by …. The A slot is the work: 以教书为生 · 以写作为生 · 以捕鱼为生. Compare 以…为业 (the trade itself).",
  "他以教书为生。", "他以教書為生。",
  "Tā yǐ jiāoshū wéi shēng.",
  "He makes a living by teaching."),
 ("为首", "為首", "wéi shǒu", "headed by; led by", "verb",
  "以…为首 = headed by …. The A slot is the leader, and the phrase modifies the group: 以他为首的三个人 · 以美国为首的联盟.",
  "以他为首的三个人反对这个计划。", "以他為首的三個人反對這個計劃。",
  "Yǐ tā wéi shǒu de sān ge rén fǎnduì zhège jìhuà.",
  "The three people headed by him opposed this plan."),
 ("为由", "為由", "wéi yóu", "on the grounds of; using as the reason", "verb",
  "以…为由 = on the grounds of …. The reason is usually an excuse. Formal; 以…为借口 is blunter and always negative.",
  "他以生病为由，没有出席会议。", "他以生病為由，沒有出席會議。",
  "Tā yǐ shēngbìng wéi yóu, méiyǒu chūxí huìyì.",
  "He did not attend the meeting, on the grounds of illness."),
 ("为重", "為重", "wéi zhòng", "to put first; to give priority to", "verb",
  "以…为重 = put … first. 重 is zhòng here. Common A slots: 以大局为重 · 以国事为重 · 以健康为重.",
  "一切都要以大局为重。", "一切都要以大局為重。",
  "Yíqiè dōu yào yǐ dàjú wéi zhòng.",
  "Everything must put the overall situation first."),
 ("为名", "為名", "wéi míng", "under the name of; in the name of", "verb",
  "以…为名 = under the name of …. The stated purpose hides the real one: 以考察为名 · 以吊丧为名.",
  "他以考察为名，其实是去旅游。", "他以考察為名，其實是去旅遊。",
  "Tā yǐ kǎochá wéi míng, qíshí shì qù lǚyóu.",
  "He travelled under the name of an inspection, but in fact he went sightseeing."),
 ("为准", "為準", "wéi zhǔn", "to take as the standard; shall prevail", "verb",
  "以…为准 = … shall prevail. Contracts and rules use it for the version that wins: 以合同为准 · 以实物为准 · 以最新公告为准.",
  "两个日期不同，以合同上的为准。", "兩個日期不同，以合同上的為準。",
  "Liǎng ge rìqī bùtóng, yǐ hétong shàng de wéi zhǔn.",
  "The two dates differ; the one on the contract shall prevail."),
 ("为贵", "為貴", "wéi guì", "to value most; to prize", "verb",
  "以…为贵 = value … most. Two set phrases carry it: 以和为贵 harmony is to be prized · 物以稀为贵 the rarer a thing is, the more it is worth.",
  "中国人常说以和为贵。", "中國人常說以和為貴。",
  "Zhōngguórén cháng shuō yǐ hé wéi guì.",
  "Chinese people often say that harmony is to be prized."),
 ("为界", "為界", "wéi jiè", "with … as the boundary", "verb",
  "以…为界 = with … as the boundary. Geography and dates both: 以黄河为界 · 以本月底为界.",
  "两国以这条河为界。", "兩國以這條河為界。",
  "Liǎng guó yǐ zhè tiáo hé wéi jiè.",
  "The two countries take this river as their boundary."),
 ("为荣", "為榮", "wéi róng", "to take pride in", "verb",
  "以…为荣 = take pride in …. Its opposite is 以…为耻. Also 引以为荣 / 引以为傲.",
  "他以自己的父亲为荣。", "他以自己的父親為榮。",
  "Tā yǐ zìjǐ de fùqīn wéi róng.",
  "He takes pride in his father."),
 ("为业", "為業", "wéi yè", "to make one's trade; to work as", "verb",
  "以…为业 = make … your trade. Names the occupation: 以捕鱼为业 · 以医为业. 以…为生 names how you eat.",
  "他家三代以捕鱼为业。", "他家三代以捕魚為業。",
  "Tā jiā sān dài yǐ bǔyú wéi yè.",
  "His family worked as fishermen for three generations."),
 ("为乐", "為樂", "wéi lè", "to take pleasure in", "verb",
  "以…为乐 = take pleasure in …. 乐 is lè. Often of a habit others find odd: 以助人为乐 · 以读书为乐.",
  "他以帮助别人为乐。", "他以幫助別人為樂。",
  "Tā yǐ bāngzhù biérén wéi lè.",
  "He takes pleasure in helping others."),
 ("为家", "為家", "wéi jiā", "to make one's home of", "verb",
  "以…为家 = make your home of …. Set phrase 四海为家 at home anywhere. Also 以校为家 · 以车为家.",
  "他常年出差，以车为家。", "他常年出差，以車為家。",
  "Tā chángnián chūchāi, yǐ chē wéi jiā.",
  "He travels all year and makes his car his home."),
 ("为鉴", "為鑒", "wéi jiàn", "to take as a lesson; to learn from", "verb",
  "以…为鉴 = take … as a lesson. 鉴 is a bronze mirror. 以史为鉴 learn from history · 引以为鉴. The variant 以…为镜 is older: 以人为镜.",
  "我们要以历史为鉴。", "我們要以歷史為鑒。",
  "Wǒmen yào yǐ lìshǐ wéi jiàn.",
  "We must learn our lesson from history."),
 ("为序", "為序", "wéi xù", "to order by; arranged by", "verb",
  "以…为序 = ordered by …. Lists and indexes: 以姓氏笔画为序 · 以时间为序.",
  "名单以姓氏笔画为序。", "名單以姓氏筆畫為序。",
  "Míngdān yǐ xìngshì bǐhuà wéi xù.",
  "The list is ordered by the stroke count of the surnames."),
 ("为耻", "為恥", "wéi chǐ", "to treat as a disgrace", "verb",
  "以…为耻 = treat … as a disgrace. The opposite of 以…为荣, and the two often appear together.",
  "他以说谎为耻。", "他以說謊為恥。",
  "Tā yǐ shuōhuǎng wéi chǐ.",
  "He treats lying as a disgrace."),
 ("为师", "為師", "wéi shī", "to take as one's teacher", "verb",
  "以…为师 = take … as your teacher. 以自然为师 · 以吏为师. 为师 alone is how a master says \"I\" to a student.",
  "他以自然为师。", "他以自然為師。",
  "Tā yǐ zìrán wéi shī.",
  "He takes nature as his teacher."),
 ("为食", "為食", "wéi shí", "to feed on", "verb",
  "以…为食 = feed on …. Biology register, about animals: 青蛙以昆虫为食 · 熊猫以竹子为食.",
  "青蛙以昆虫为食。", "青蛙以昆蟲為食。",
  "Qīngwā yǐ kūnchóng wéi shí.",
  "Frogs feed on insects."),
 ("为限", "為限", "wéi xiàn", "with … as the limit; not beyond", "verb",
  "以…为限 = with … as the limit. Deadlines and caps: 以本周五为限 · 以三杯为限.",
  "报名以本周五为限。", "報名以本週五為限。",
  "Bàomíng yǐ běn zhōuwǔ wéi xiàn.",
  "Registration closes this Friday at the latest."),
 ("以退为进", "以退為進", "yǐ tuì wéi jìn", "to retreat in order to advance (idiom)", "idiom",
  "A fixed A-B pair inside the frame: both slots hold a verb. You give ground on purpose to gain more later. Compare 以攻为守.",
  "他这是以退为进的策略。", "他這是以退為進的策略。",
  "Tā zhè shì yǐ tuì wéi jìn de cèlüè.",
  "This is his strategy of retreating in order to advance."),
 ("以攻为守", "以攻為守", "yǐ gōng wéi shǒu", "to attack as a form of defence (idiom)", "idiom",
  "A fixed A-B pair inside the frame: both slots hold a verb. You defend yourself by striking first. Compare 以退为进.",
  "球队采取以攻为守的打法。", "球隊採取以攻為守的打法。",
  "Qiúduì cǎiqǔ yǐ gōng wéi shǒu de dǎfǎ.",
  "The team plays an attacking style as its defence."),
 ("以邻为壑", "以鄰為壑", "yǐ lín wéi hè", "to shift your problem onto others (idiom)", "idiom",
  "壑 is a drainage ditch: you send your flood water into the neighbour's field. Always critical. Used of trade policy and of pollution.",
  "这种做法是以邻为壑。", "這種做法是以鄰為壑。",
  "Zhè zhǒng zuòfǎ shì yǐ lín wéi hè.",
  "This practice shifts the problem onto the neighbours."),
]

# already in Archive: move the forward card into Main, unsuspend it, tag it
PROMOTE = ["为己任", "以和为贵", "以史为鉴"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--db", default=COL)
    args = ap.parse_args()

    col = Collection(args.db)
    try:
        model = col.models.by_name(NOTETYPE)
        assert model, NOTETYPE
        main_did = deck_registry.new_words_deck_id(col)
        rev_did = deck_registry.deck_id_for(col, deck_registry.PRODUCTION)
        print(f"target deck id {main_did} ({col.decks.name(main_did)}), "
              f"production {col.decks.name(rev_did)}")

        # --- refuse duplicates ------------------------------------------------
        created, skipped = [], []
        for row in CARDS:
            word = row[0]
            if col.db.list("SELECT id FROM notes WHERE mid=? AND sfld=?", model["id"], word):
                skipped.append(word)
                continue
            print(f"\n=== {word}  {row[2]}  [{row[4]}]")
            print(f"    meaning : {row[3]}")
            print(f"    notes   : {row[5]}")
            print(f"    sentence: {row[6]}")
            print(f"              {row[8]}")
            print(f"              {row[9]}")
            if not args.apply:
                continue
            note = col.new_note(model)
            note["Simplified"] = row[0]
            note["Traditional"] = row[1]
            note["Pinyin"] = row[2]
            note["Meaning"] = row[3]
            note["PartOfSpeech"] = row[4]
            note["Notes"] = row[5]
            note["SentenceSimplified"] = row[6]
            note["SentenceTraditional"] = row[7]
            note["SentencePinyin"] = row[8]
            note["SentenceMeaning"] = row[9]
            note.tags = list(TAGS) + (["type::Chengyu"] if row[4] == "idiom" else [])
            col.add_note(note, main_did)
            created.append((word, note.id))
            # route ord1 out of the study deck and suspend it, like every other note
            rev = [c.id for c in note.cards() if c.ord == 1]
            if rev:
                col.set_deck(rev, rev_did)
                col.sched.suspend_cards(rev)

        # --- promote the three that already exist -----------------------------
        promoted = []
        for word in PROMOTE:
            nids = col.db.list("SELECT id FROM notes WHERE mid=? AND sfld=?", model["id"], word)
            if not nids:
                print(f"!! {word}: no {NOTETYPE} note")
                continue
            for nid in nids:
                note = col.get_note(nid)
                fwd = [c for c in note.cards() if c.ord == 0]
                print(f"\n=== promote {word} (note {nid}) "
                      f"{[(c.ord, col.decks.name(c.did), c.queue) for c in note.cards()]}")
                if not args.apply:
                    continue
                for t in TAGS:
                    if t not in note.tags:
                        note.tags.append(t)
                col.update_note(note)
                if fwd:
                    col.set_deck([c.id for c in fwd], main_did)
                    col.sched.unsuspend_cards([c.id for c in fwd])
                rev = [c.id for c in note.cards() if c.ord == 1]
                if rev:
                    col.set_deck(rev, rev_did)
                    col.sched.suspend_cards(rev)
                promoted.append((word, nid))

        print(f"\nskipped (note already exists): {skipped}")
        if not args.apply:
            print(f"DRY RUN — would create {len(CARDS) - len(skipped)}, promote {len(PROMOTE)}")
            return

        # --- verify in this window -------------------------------------------
        print(f"\ncreated {len(created)}, promoted {len(promoted)}")
        bad = []
        for word, nid in created + promoted:
            note = col.get_note(nid)
            states = [(c.ord, col.decks.name(c.did), c.queue) for c in note.cards()]
            fwd = [s for s in states if s[0] == 0]
            ok = fwd and fwd[0][1] == col.decks.name(main_did) and fwd[0][2] == 0
            other = [s for s in states if s[0] != 0 and s[2] != -1]
            if not ok or other:
                bad.append((word, states))
            print(f"  {word:<6} {states}")
        print(f"\nVERIFY: {len(created)+len(promoted)} notes, "
              f"{'ALL forward cards new in Main, all others suspended' if not bad else f'PROBLEMS {bad}'}")
    finally:
        col.close()


if __name__ == "__main__":
    main()
