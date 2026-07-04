#!/usr/bin/env python3
"""Generate Hanly-style character mnemonics via Claude. No collection access.
Usage: char_gen.py 残 酷 想 ...    (writes freq_data/chars/char_cards.json)"""
import sys, json, re, os
from pypinyin import pinyin, Style
from wordfreq import zipf_frequency
import anthropic

ROOT="/home/vincent/anki-headless"
CONFIG=json.load(open(f"{ROOT}/.bot_config.json"))
client=anthropic.Anthropic(api_key=CONFIG["anthropic_api_key"])
MODEL="claude-sonnet-4-5-20250929"   # reuse bot's proven model; bump to a newer sonnet anytime

# CEDICT single-char lookup: simp -> (trad, gloss)
ced={}
with open("/home/vincent/chinese-projects/dong-chinese/Resources/cedict_ts.u8") as f:
    for line in f:
        if line.startswith("#"): continue
        m=re.match(r"(\S+) (\S+) \[([^\]]*)\] /(.+)/",line)
        if m and len(m.group(2))==1 and m.group(2) not in ced:
            ced[m.group(2)]=(m.group(1),m.group(4).replace("/","; "))

chars=[c for c in sys.argv[1:] if re.fullmatch(r"[一-鿿]",c)]
items=[]
for c in chars:
    py=pinyin(c,style=Style.TONE)[0][0]
    trad,gloss=ced.get(c,(c,""))
    items.append({"char":c,"pinyin":py,"meaning":gloss[:80],"trad":trad})

prompt=f"""You create Chinese character mnemonics in the style of the Hanly app, for a heritage learner improving reading.
For each character, produce:
- components: the visual decomposition, naming each component with a concrete image/meaning, e.g. "歹 (bare bones) + 戋 (two spears 戈)".
- mnemonic: a vivid, concise 1-2 sentence story that links the components to the character's MEANING. When the pronunciation is memorable, weave in a sound-actor (e.g. 酷 kù -> "cool"). Keep it punchy and visual.

Characters (JSON):
{json.dumps(items,ensure_ascii=False)}

Return ONLY a JSON array, one object per character IN THE SAME ORDER, each with keys: char, components, mnemonic."""

resp=client.messages.create(model=MODEL,max_tokens=3000,messages=[{"role":"user","content":prompt}])
text=resp.content[0].text
mjson=re.search(r"\[.*\]",text,re.S)
data=json.loads(mjson.group(0))
# attach pinyin/meaning/trad/freq
by={d["char"]:d for d in data}
out=[]
for it in items:
    d=by.get(it["char"],{})
    out.append({**it,
        "components":d.get("components",""),
        "mnemonic":d.get("mnemonic",""),
        "zipf":round(zipf_frequency(it["char"],"zh"),2)})
os.makedirs(f"{ROOT}/freq_data/chars",exist_ok=True)
json.dump(out,open(f"{ROOT}/freq_data/chars/char_cards.json","w"),ensure_ascii=False,indent=1)
for o in out:
    print(f"\n{o['char']}  {o['pinyin']}  — {o['meaning'][:50]}")
    print(f"  components: {o['components']}")
    print(f"  mnemonic:   {o['mnemonic']}")
print(f"\nwrote {len(out)} -> freq_data/chars/char_cards.json")
