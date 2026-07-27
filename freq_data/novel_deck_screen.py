#!/usr/bin/env python3
"""Drop character names and non-words from the novel deck pool.

Frequency ranking alone puts 黑熊 at the top of the deck — a real dictionary word
("Asiatic black bear") that in this novel is a character's nickname, alongside 潇潇,
黑子, 人鼠, 地狗. jieba's name tagger misses them precisely because they are ordinary
words; the only reliable signal is how the sentences use them, so this shows the model
two real sentences per candidate and asks.

Conservative on purpose: keep unless the evidence says otherwise. A name that slips
through costs one wasted card; a real word wrongly dropped never gets studied.

  novel_deck_apply.py --dump-pool /tmp/pool.json --col <copy>
  novel_deck_screen.py --pool /tmp/pool.json      -> freq_data/novel_deck_screen.json
"""
import argparse
import json
from pathlib import Path

import anthropic

ROOT = Path("/home/vincent/anki-headless")
CONFIG = json.loads((ROOT / ".bot_config.json").read_text())
MODEL = "claude-opus-5"
BATCH = 50

PROMPT = """Each entry below is a candidate flashcard for a learner reading the Chinese
web novel 《十日终焉·囚笼》. Each shows the word, its dictionary gloss, how many times it
occurs in the book, and one or two sentences from the book that use it.

Decide, for each, whether it is worth a vocabulary card.

Drop it if:
- in this book it is a character's name or nickname, a place name, or the name of a
  group or organisation. Several characters here are nicknamed after animals or with
  reduplicated syllables, so a word can be an ordinary dictionary word and still be a
  name in these sentences. Judge from the sentences, not the gloss.
- it is not really a word — a segmentation artifact, or a transparent compound whose
  meaning is just its characters added together and which no dictionary-user would need.

Keep everything else, including words that look easy. When the sentences are ambiguous,
keep it. Do not drop a word merely because it is uncommon, literary, or specific to
this book's setting — that is exactly the vocabulary being studied.

Return a verdict for every entry, in the order given."""

SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "keep": {"type": "boolean"},
                    "reason": {"type": "string",
                               "description": "Only when dropping: 'name' or 'not a word', "
                                              "plus a few words of justification."},
                },
                "required": ["word", "keep", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}


def screen(client, batch):
    lines = []
    for e in batch:
        lines.append(f"{e['word']} — {e['gloss']} — {e['n']}× in the book")
        for s in e["sentences"][:2]:
            lines.append(f"    · {s}")
    msg = PROMPT + "\n\n" + "\n".join(lines)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": msg}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("refused")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)["verdicts"], resp.usage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", required=True)
    ap.add_argument("--out", default=str(ROOT / "freq_data/novel_deck_screen.json"))
    a = ap.parse_args()

    pool = json.loads(Path(a.pool).read_text())
    client = anthropic.Anthropic(api_key=CONFIG["anthropic_api_key"])

    verdicts, tin, tout = [], 0, 0
    for i in range(0, len(pool), BATCH):
        v, u = screen(client, pool[i:i + BATCH])
        verdicts += v
        tin += u.input_tokens
        tout += u.output_tokens
        print(f"  screened {min(i+BATCH, len(pool))}/{len(pool)}")

    by_word = {e["word"]: e for e in pool}
    drop = [{"word": v["word"], "reason": v["reason"], "n": by_word.get(v["word"], {}).get("n")}
            for v in verdicts if not v["keep"] and v["word"] in by_word]

    Path(a.out).write_text(json.dumps(
        {"pool": len(pool), "dropped": len(drop), "drop": drop},
        ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n{len(drop)} of {len(pool)} dropped -> {a.out}   [in {tin} out {tout}]")
    for d in sorted(drop, key=lambda x: -(x["n"] or 0)):
        print(f"  {d['word']}  ({d['n']}×)  {d['reason']}")


if __name__ == "__main__":
    main()
