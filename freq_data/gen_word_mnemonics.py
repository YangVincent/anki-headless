#!/usr/bin/env python3
"""Generate Hanly-style word mnemonics via Claude.
Usage: gen_word_mnemonics.py <word1> <word2> ... > output.json
Output: JSON array of {word, meaning, pinyin, components, mnemonic}"""
import sys, json, re, os
from pypinyin import pinyin, Style
import anthropic

ROOT = "/home/vincent/anki-headless"
CONFIG = json.load(open(f"{ROOT}/.bot_config.json"))
client = anthropic.Anthropic(api_key=CONFIG["anthropic_api_key"])
MODEL = "claude-sonnet-4-5-20250929"

words = [w.strip() for w in sys.argv[1:] if re.fullmatch(r"[\u4e00-\u9fff\u3400-\u4dbf]{2,}", w.strip())]
if not words:
    sys.exit(0)

items = []
for w in words:
    py = " ".join(p[0] for p in pinyin(w, style=Style.TONE))
    items.append({"word": w, "pinyin": py})

prompt = f"""You create Chinese word mnemonics in the style of the Hanly app, for a heritage learner who speaks Mandarin but struggles with reading/writing. They already know these words by ear — the mnemonic's job is to make the WRITTEN form stick by decomposing it into concrete visual components.

For each word, produce:
- components: a character-by-character breakdown naming a concrete meaning/image for each character, e.g. "带(belt) + 领(neck/lead)"
- mnemonic: a vivid, concise 1-2 sentence story linking the components to the word's MEANING. Use sound-alikes when helpful. Keep it punchy and visual.

Words (JSON):
{json.dumps(items, ensure_ascii=False)}

Return ONLY a JSON array, one object per word IN THE SAME ORDER, each with keys: word, components, mnemonic."""

resp = client.messages.create(model=MODEL, max_tokens=4000, messages=[{"role": "user", "content": prompt}])
text = resp.content[0].text
mjson = re.search(r"\[.*\]", text, re.S)
data = json.loads(mjson.group(0)) if mjson else []

by = {d["word"]: d for d in data}
out = []
for it in items:
    d = by.get(it["word"], {})
    out.append({"word": it["word"], "pinyin": it["pinyin"],
                "components": d.get("components", ""),
                "mnemonic": d.get("mnemonic", "")})

json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
