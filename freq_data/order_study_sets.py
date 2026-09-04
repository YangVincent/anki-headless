#!/usr/bin/env python3
"""Pick ONE emotion word per emotional category. The rest wait.

`set::emotions` is band 0 in resort_main_queue.py, so whatever carries it comes up first.
This script decides what carries it.

THE RULE. Teaching near-synonyms together slows acquisition: the items interfere and you
finish unsure which is which. So the 57 words are grouped into emotional categories below,
and exactly one word per category goes to the front:

  * a word you are ALREADY STUDYING wins its category outright. It is in rotation, you
    know it, and a new near-synonym beside it is the confusion this rule exists to stop.
    31 of the 57 are in review, learning or relearning, so most categories are settled.
  * otherwise the commonest new word wins, by wordfreq.
  * a category whose only candidate falls under Zipf 3.0 waits. 亢奋 (excitement) is the
    one this drops: at Zipf 1.21 it is too rare to hold, and no commoner word covers it.

The winner keeps `set::emotions`. Everything else gets `set::emotions-later`, which is an
ordinary curriculum word again. `tag:set::emotions*` still finds the whole set, so nothing
becomes unaddressable and one edit to CATEGORIES reverses any call.

WHAT CHANGED ON 2026-09-04. This script used to express the same idea with four clusters
and a `liked` tag: front words gained `liked`, deferred words lost it. Two faults.

  * `liked` claimed to be a hand mark -- resort_main_queue.py's band 0 comment said "a
    hand mark beats every computed rule" -- but no hand ever set it. One run of THIS
    SCRIPT wrote all 40 at 16:34 on 2026-09-01. Vincent asked for the tag to go.
  * four clusters is not one word per category. The front set still held 怀念/思念,
    愤怒/愤慨, 轻蔑/鄙视, 恐惧/畏惧, 惋惜/遗憾 and 欣喜/欣慰/惊喜 -- the exact
    interference the clusters were meant to remove. CATEGORIES below covers all 57.

Stella An stays deferred: `next::stella-an` becomes `set::stella-an`. It scored 0.1 tokens
per card against 《十年》 -- essay vocabulary, not fiction vocabulary -- and it is worth
pulling forward only when the reading changes.

Usage: freq_data/order_study_sets.py                       (dry run)
       bash freq_data/anki_op.sh order-sets freq_data/order_study_sets.py --apply
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path("/home/vincent/anki-headless")
sys.path.insert(0, str(ROOT))

import anki.collection  # noqa: E402,F401
from anki.collection import Collection  # noqa: E402

FRONT_TAG = "set::emotions"
LATER_TAG = "set::emotions-later"
#: Dropped from the set entirely -- "consciousness; awareness" is not an emotion. It was
#: the commonest word here, so it sat at the very front. It rejoins the curriculum.
NOT_AN_EMOTION = {"意识"}
#: A category whose best candidate is rarer than this waits for a commoner one.
RARE_FLOOR = 3.0

#: Every word carrying the tag must appear exactly once. main() checks both directions and
#: refuses to write if the map and the collection disagree -- a word missing from here
#: would be silently deferred forever, which is the failure this map exists to prevent.
CATEGORIES = {
    "anxiety":       ["焦虑", "烦躁", "焦躁", "焦灼", "忐忑"],
    "fear":          ["恐惧", "畏惧", "惶恐"],
    "anger":         ["愤怒", "愤慨"],
    "sadness":       ["悲伤", "悲哀", "忧郁", "心酸", "怅然", "沮丧"],
    "despair":       ["绝望"],
    "pessimism":     ["悲观"],
    "surprise":      ["惊讶", "震惊", "诧异", "惊喜"],
    "shame/guilt":   ["惭愧", "羞愧", "内疚", "愧疚"],
    "contempt":      ["鄙视", "轻蔑"],
    "arrogance":     ["傲慢"],
    "jealousy":      ["嫉妒"],
    "loneliness":    ["孤独"],
    "emptiness":     ["空虚"],
    "inferiority":   ["自卑"],
    "bewilderment":  ["茫然"],
    "relief":        ["释怀", "释然"],
    "excitement":    ["亢奋"],
    "feeling wronged": ["委屈", "憋屈"],
    "embarrassment": ["尴尬"],
    "breakdown":     ["崩溃"],
    "resignation":   ["无奈"],
    "boredom":       ["厌烦"],
    "gratitude":     ["感激"],
    "gratification": ["欣慰"],
    "joy":           ["欣喜"],
    "pride":         ["自豪"],
    "modesty":       ["谦虚"],
    "admiration":    ["敬佩"],
    "longing":       ["渴望"],
    "missing":       ["怀念", "思念"],
    "tenderness":    ["心疼"],
    "regret":        ["遗憾", "惋惜"],
    "panic":         ["慌张"],
    "mania":         ["疯狂"],
}


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def main():
    from wordfreq import zipf_frequency
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "collection.anki2"))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    col = Collection(args.db)
    try:
        # Both tags, so a second run sees the set it created last time and stays idempotent.
        nid_of, studied = {}, {}
        for tag in (FRONT_TAG, LATER_TAG):
            for nid in col.find_notes(f"tag:{tag}"):
                word = strip_html(col.get_note(nid).fields[0])
                nid_of[word] = nid
                # type 0 is new; 1/2/3 are learning, review and relearning. A word with any
                # card out of the new queue is one you already study.
                studied[word] = any(c.type != 0 for c in col.get_note(nid).cards()
                                    if c.ord == 0)

        mapped = [w for ws in CATEGORIES.values() for w in ws]
        dupes = {w for w in mapped if mapped.count(w) > 1}
        unmapped = sorted(set(nid_of) - set(mapped) - NOT_AN_EMOTION)
        absent = sorted(set(mapped) - set(nid_of))
        if dupes or unmapped or absent:
            print(f"REFUSING: CATEGORIES disagrees with the collection.")
            if dupes:    print(f"  in two categories: {' '.join(sorted(dupes))}")
            if unmapped: print(f"  tagged but not in any category: {' '.join(unmapped)}")
            if absent:   print(f"  in a category but not tagged: {' '.join(absent)}")
            raise SystemExit(1)

        front, defer, report = set(), set(), []
        for cat, words in CATEGORIES.items():
            have = [w for w in words if w in nid_of]
            if not have:
                continue
            # A word already in rotation wins outright; else the commonest new one.
            pool = [w for w in have if studied[w]] or have
            win = max(pool, key=lambda w: (zipf_frequency(w, "zh"), w))
            z = zipf_frequency(win, "zh")
            if not studied[win] and z < RARE_FLOOR:
                # No candidate worth holding. The whole category waits.
                defer.update(have)
                report.append((cat, None, win, z, have))
                continue
            front.add(win)
            defer.update(w for w in have if w != win)
            report.append((cat, win, None, z, have))

        new_front = sorted(w for w in front if not studied[w])
        print(f"{len(nid_of)} words · {len(CATEGORIES)} categories · "
              f"front {len(front)} · deferred {len(defer)}\n")
        for cat, win, dropped, z, have in report:
            mark = "STUDIED" if win and studied[win] else "new"
            head = f"{win} ({mark})" if win else f"-- none: {dropped} is Zipf {z:.2f}"
            rest = " ".join(w for w in have if w != (win or dropped))
            print(f"  {cat:<16} {head:<18} {('waits: ' + rest) if rest else ''}")
        print(f"\nNEW cards reaching the front ({len(new_front)}): {' '.join(new_front)}")
        print(f"tag:liked notes to clear: {len(col.find_notes('tag:liked'))}")

        if not args.apply:
            print("\n(dry run; nothing written)")
            return

        for word, nid in nid_of.items():
            note = col.get_note(nid)
            note.remove_tag("liked")           # the tag is retired; see the docstring
            if word in NOT_AN_EMOTION:
                note.remove_tag(FRONT_TAG)
                note.remove_tag(LATER_TAG)
            elif word in front:
                note.remove_tag(LATER_TAG)
                if FRONT_TAG not in note.tags:
                    note.add_tag(FRONT_TAG)
            else:
                note.remove_tag(FRONT_TAG)
                if LATER_TAG not in note.tags:
                    note.add_tag(LATER_TAG)
            col.update_note(note)

        # `liked` lived only on emotion notes, but scope the clear to the tag rather than
        # to this set: "none of my cards should carry liked" is the requirement, and a
        # note outside the set would otherwise keep it and stay in band 0 unnoticed.
        for nid in col.find_notes("tag:liked"):
            note = col.get_note(nid)
            note.remove_tag("liked")
            col.update_note(note)

        for nid in col.find_notes("tag:next::stella-an"):
            note = col.get_note(nid)
            note.remove_tag("next::stella-an")
            if "set::stella-an" not in note.tags:
                note.add_tag("set::stella-an")
            col.update_note(note)

        print(f"\nverify: {FRONT_TAG} notes {len(col.find_notes(f'tag:{FRONT_TAG}'))} "
              f"(want {len(front)})")
        print(f"verify: {LATER_TAG} notes {len(col.find_notes(f'tag:{LATER_TAG}'))} "
              f"(want {len(defer)})")
        print(f"verify: tag:liked notes {len(col.find_notes('tag:liked'))} (want 0)")
        print(f"verify: 意识 still in the set: "
              f"{len(col.find_notes(f'意识 tag:{FRONT_TAG}'))} (want 0)")
        print(f"verify: next::stella-an {len(col.find_notes('tag:next::stella-an'))} (want 0)")
        print(f"verify: book::十年 untouched {len(col.find_notes('tag:book::十年'))}")
        print("\nNEXT: bash freq_data/anki_op.sh resort-main "
              "freq_data/resort_main_queue.py --apply")
    finally:
        col.close()


if __name__ == "__main__":
    main()
