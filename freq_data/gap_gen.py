#!/usr/bin/env python3
"""Generate component-decomposition mnemonics for the not-in-Hanly gap chars.
Reads freq_data/chars/gap_chars.json (from gap_build.py), batches to Claude,
writes/accumulates freq_data/chars/gap_cards.json. RESUMABLE: already-generated
chars are skipped, so re-running after a crash never re-spends. No collection access.
Usage: gap_gen.py [--limit N] [--batch 15]
"""
import sys, json, re, os, time
import anthropic

ROOT = "/home/vincent/anki-headless"
CONFIG = json.load(open(f"{ROOT}/.bot_config.json"))
client = anthropic.Anthropic(api_key=CONFIG["anthropic_api_key"])
MODEL = "claude-sonnet-4-5-20250929"  # same model char_gen.py uses

LIMIT = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
BATCH = int(sys.argv[sys.argv.index("--batch") + 1]) if "--batch" in sys.argv else 15

src = json.load(open(f"{ROOT}/freq_data/chars/gap_chars.json"))
if LIMIT:
    src = src[:LIMIT]

out_path = f"{ROOT}/freq_data/chars/gap_cards.json"
done = {}
if os.path.exists(out_path):
    for o in json.load(open(out_path)):
        done[o["char"]] = o

todo = [it for it in src if it["char"] not in done]
print(f"{len(done)} already generated, {len(todo)} to do (of {len(src)} in scope)")

PROMPT = """You create Chinese character mnemonics in the style of the Hanly app, for a heritage learner who speaks Mandarin but is weak at READING. He already knows these words by ear; the mnemonic's job is to make the WRITTEN character stick by decomposing it into concrete visual components.
For each character, produce:
- components: the visual decomposition, naming each component with a concrete image/meaning, e.g. "歹 (bare bones) + 戋 (two spears 戈)". Use real sub-components of the character.
- mnemonic: a vivid, concise 1-2 sentence story linking the components to the character's MEANING. When the pronunciation is memorable, weave in a sound-actor (e.g. 酷 ku4 -> "cool"). Punchy and visual.

Characters (JSON):
{items}

Return ONLY a JSON array, one object per character IN THE SAME ORDER, each with keys: char, components, mnemonic."""

def gen_batch(items):
    payload = [{"char": it["char"], "pinyin": it["pinyin"],
                "meaning": it["meaning"], "trad": it["trad"]} for it in items]
    resp = client.messages.create(
        model=MODEL, max_tokens=4000,
        messages=[{"role": "user",
                   "content": PROMPT.format(items=json.dumps(payload, ensure_ascii=False))}])
    text = resp.content[0].text
    mjson = re.search(r"\[.*\]", text, re.S)
    data = json.loads(mjson.group(0))
    return {d["char"]: d for d in data}

for i in range(0, len(todo), BATCH):
    chunk = todo[i:i + BATCH]
    try:
        by = gen_batch(chunk)
    except Exception as e:
        print(f"  batch {i//BATCH} FAILED: {e} — saving progress, re-run to continue")
        break
    for it in chunk:
        d = by.get(it["char"], {})
        done[it["char"]] = {
            **it,
            "components": d.get("components", ""),
            "mnemonic": d.get("mnemonic", ""),
        }
    # persist after every batch (resumable)
    ordered = [done[it["char"]] for it in src if it["char"] in done]
    json.dump(ordered, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(f"  batch {i//BATCH}: +{len(chunk)} ({len(done)} total) saved")
    time.sleep(0.5)

ordered = [done[it["char"]] for it in src if it["char"] in done]
json.dump(ordered, open(out_path, "w"), ensure_ascii=False, indent=1)
print(f"\nwrote {len(ordered)} -> freq_data/chars/gap_cards.json")
# show a few
for o in ordered[:6]:
    print(f"\n{o['char']}  {o['pinyin']}  — {o['meaning'][:45]}")
    print(f"  components: {o['components']}")
    print(f"  mnemonic:   {o['mnemonic']}")
