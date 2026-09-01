#!/usr/bin/env python3
"""Rewrite the descriptions on the HSK cards that keep failing.

118 cards have lapsed 3+ times. 112 of them already have an example sentence, so
context is not what is missing. Looking at what is actually on them, they fail for
three different reasons and need three different fixes:

  connectives   然而 is glossed "however; yet; but" — and so are 但是, 可是 and 不过.
                Nothing on the card distinguishes them, so there is nothing to recall.
                Fix: say what job it does and how it differs from its neighbours.

  abstract words  原则 "principle" is a correct translation with no hook.
                Fix: the phrases it actually turns up in.

  bare characters  22 of the 118 are single characters, and several are simply wrong:
                幽 is glossed "Humor", which is 幽默's meaning, not 幽's; 符's example
                sentence is an anime fragment; some have raw HTML in the pinyin field.
                Fix: the character's own meaning, plus the words it lives inside.

Writes proposals for review. Nothing touches the collection — run leech_apply.py after
reading them.

  leech_rewrite.py [--min-lapses 3] [--out freq_data/leech_rewrite.json]
"""
import sys
sys.path.insert(0, "/home/vincent/anki-headless")
import decks as deck_registry  # noqa: E402
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import anthropic

ROOT = Path("/home/vincent/anki-headless")
CONFIG = json.loads((ROOT / ".bot_config.json").read_text())
MODEL = "claude-opus-5"
BATCH = 20
DECK = deck_registry.RECOGNITION_DECKS[0]

PROMPT = """These are Chinese flashcards that a learner keeps failing — each has lapsed
several times. He is a heritage speaker: he reads almost all characters fluently and his
listening is native-ish, but he is studying written and formal vocabulary. Assume he does
not need pronunciation help or basic characters explained.

For each card, write a description that would let him actually recall the word, rather
than a dictionary translation. Diagnose why the current card fails, then fix that.

The three failure modes, and what each needs:

1. A connective or function word whose gloss is shared with several others (然而, 以及,
   此外, 进而, 从而 all gloss to "however" / "in addition" / "thus"). A translation cannot
   distinguish them. Write what job it does in a sentence — what it connects, where it
   sits, and how formal it is — and name the specific words it gets confused with and the
   difference. That contrast is the whole point of the card.

2. An abstract word with a correct but hookless translation (原则 "principle"). Give the
   handful of phrases it genuinely occurs in, so it is anchored to a use rather than to
   an English word.

3. A single character. Two very different cases here, and the entry says which it is:

   - The character is not a word on its own in modern Chinese (衬, 肤, 厌, 幽, 舒, 污,
     航, 符, 允, 激 — they live inside 衬衫, 皮肤, 讨厌, 幽默 …). Asking him to recall a
     standalone meaning is asking for something that never occurs, which is why these
     fail hardest, and why some glosses are simply wrong — 幽 glossed "Humor" is 幽默's
     meaning, not 幽's. Set `recommend` to "learn-in-word": name the one or two words he
     should study instead, give the character's real meaning as background for guessing
     unfamiliar compounds, and do not pretend it is usable alone.

   - The character does stand alone as a word (矮, 弃, 误, 杂, 矿, 键, 译, 脱, 祝, 降,
     码, 演). Set `recommend` to "keep": these are legitimate cards, so fix the
     description and say what it means as a standalone word versus inside compounds.

Rules:
- Write in plain English, the way you would explain it to someone in conversation. No
  grammar jargon unless it genuinely is the clearest way to say it.
- Be concrete and short. Two sentences of description beats a paragraph.
- Only give a contrast when there is a real confusion to resolve. Do not manufacture one.
- If the existing gloss is wrong or misleading, say so in `problem` and correct it.
- Collocations must be real and common. Three good ones beat six padded ones.
- The example sentence should be natural, ordinary modern Chinese, and should show the
  word doing its characteristic job. Replace the existing one if it is an anime or game
  fragment, or if it does not illustrate anything."""

SCHEMA = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "kind": {"type": "string", "enum": ["connective", "abstract",
                                                        "character", "other"]},
                    "problem": {"type": "string",
                                "description": "Why the current card fails, one line. "
                                               "Say so plainly if the gloss is wrong."},
                    "meaning": {"type": "string",
                                "description": "The replacement description: what the word "
                                               "means and what job it does. Plain English."},
                    "contrast": {"type": "string",
                                 "description": "How it differs from the words it is "
                                                "confused with. Empty when there is no "
                                                "genuine confusion."},
                    "collocations": {"type": "array", "items": {"type": "string"},
                                     "description": "Real phrases it occurs in — for a "
                                                    "character, the words built from it. "
                                                    "Each as 词 (pinyin) — meaning."},
                    "sentence": {"type": "string", "description": "Example sentence, Chinese."},
                    "sentence_meaning": {"type": "string", "description": "Its translation."},
                    "recommend": {"type": "string", "enum": ["keep", "learn-in-word"],
                                  "description": "'learn-in-word' only for a character that "
                                                 "is not a word on its own — the card should "
                                                 "be retired in favour of the words below."},
                    "study_instead": {"type": "array", "items": {"type": "string"},
                                      "description": "For 'learn-in-word': the word(s) to "
                                                     "study in its place."},
                },
                "required": ["word", "kind", "problem", "meaning", "contrast",
                             "collocations", "sentence", "sentence_meaning",
                             "recommend", "study_instead"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cards"],
    "additionalProperties": False,
}


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def leeches(col, min_lapses):
    did = col.decks.id_for_name(DECK)
    per = defaultdict(lambda: [0, 0])
    for cid, ease in col.db.all("select r.cid, r.ease from revlog r "
                                "join cards c on c.id=r.cid where c.did=? and r.type=1", did):
        per[cid][0] += 1
        per[cid][1] += (ease == 1)
    out = []
    for cid, (rv, ap) in sorted(per.items(), key=lambda kv: -kv[1][1]):
        if ap < min_lapses:
            continue
        note = col.get_card(cid).note()
        d = dict(note.items())
        out.append({"nid": note.id, "word": d["Simplified"],
                    "pinyin": strip_html(d.get("Pinyin", "")),
                    "meaning": strip_html(d.get("Meaning", "")),
                    "pos": d.get("PartOfSpeech", ""),
                    "sentence": strip_html(d.get("SentenceSimplified", "")),
                    "lapses": ap, "reviews": rv})
    return out


def rewrite(client, batch):
    lines = []
    for e in batch:
        lines.append(f"{e['word']} ({e['pinyin']}) — failed {e['lapses']} of {e['reviews']} times")
        lines.append(f"    current gloss: {e['meaning'] or '(none)'}")
        if e["pos"]:
            lines.append(f"    tagged as: {e['pos']}")
        lines.append(f"    current sentence: {e['sentence'] or '(none)'}")
    resp = client.messages.create(
        model=MODEL, max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": PROMPT + "\n\n" + "\n".join(lines)}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("refused")
    return json.loads(next(b.text for b in resp.content if b.type == "text"))["cards"], resp.usage


def main():
    from anki.collection import Collection

    ap = argparse.ArgumentParser()
    ap.add_argument("--min-lapses", type=int, default=3)
    ap.add_argument("--col", default=str(ROOT / "collection.anki2"))
    ap.add_argument("--out", default=str(ROOT / "freq_data/leech_rewrite.json"))
    a = ap.parse_args()

    col = Collection(a.col)
    try:
        cards = leeches(col, a.min_lapses)
    finally:
        col.close()
    print(f"{len(cards)} cards with {a.min_lapses}+ lapses")

    client = anthropic.Anthropic(api_key=CONFIG["anthropic_api_key"])
    done, tin, tout = [], 0, 0
    for i in range(0, len(cards), BATCH):
        got, u = rewrite(client, cards[i:i + BATCH])
        done += got
        tin += u.input_tokens
        tout += u.output_tokens
        print(f"  rewritten {min(i + BATCH, len(cards))}/{len(cards)}")

    by_word = {c["word"]: c for c in cards}
    for d in done:
        src = by_word.get(d["word"], {})
        d["nid"] = src.get("nid")
        d["lapses"] = src.get("lapses")
        d["was"] = src.get("meaning")

    Path(a.out).write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    kinds = defaultdict(int)
    for d in done:
        kinds[d["kind"]] += 1
    print(f"\n{len(done)} rewritten -> {a.out}   [in {tin} out {tout}]")
    print("  " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    wrong = [d for d in done if re.search(r"wrong|incorrect|misleading|not what",
                                          d["problem"], re.I)]
    print(f"  {len(wrong)} cards whose existing gloss is wrong or misleading: "
          + " ".join(d["word"] for d in wrong))


if __name__ == "__main__":
    main()
