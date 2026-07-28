#!/usr/bin/env python3
"""Build an offline character-decomposition dataset.

Sources (both public, downloaded to freq_data/ids/):
  ids.txt         - CHISE/cjkvi-ids, IDS strings for ~89k CJK chars
  dictionary.txt  - makemeahanzi, decomposition + etymology (semantic/phonetic roles)

Writes freq_data/ids/decomp.json:
  { char: {"ids": str, "direct": [chars], "closure": [chars],
           "radical": str, "etymology": {...}|None, "definition": str} }

`closure` is the recursive component set (all levels), with radical variants
normalised (衤->衣, 饣->食, ...), so a claimed component can be checked against it.
"""
import json, re, os, sys
from collections import defaultdict

ROOT = "/home/vincent/anki-headless"
SRC = os.environ.get("DECOMP_SRC", f"{ROOT}/freq_data/ids")

IDC = set("⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻")          # ideographic description characters
def is_cjk(c):
    """a real character/component, not an IDS operator or stray marker"""
    if c in IDC or c in "^$&*?":
        return False
    o = ord(c)
    return (0x4E00 <= o <= 0x9FFF        # unified
            or 0x3400 <= o <= 0x4DBF     # ext A
            or 0x2E80 <= o <= 0x2EFF     # radicals supplement
            or 0x2F00 <= o <= 0x2FDF     # kangxi radicals
            or 0x31C0 <= o <= 0x31EF     # strokes
            or 0x20000 <= o <= 0x2A6DF)  # ext B

# radical variants -> canonical form, so "衤" counts as "衣"
VARIANT = {
    "衤": "衣", "礻": "示", "饣": "食", "钅": "金", "刂": "刀", "辶": "辵",
    "忄": "心", "扌": "手", "氵": "水", "犭": "犬", "纟": "糸", "讠": "言",
    "灬": "火", "艹": "艸", "亻": "人", "冫": "冰", "阝": "阜", "⻖": "阜",
    "月": "肉", "𤣩": "玉", "王": "玉", "罒": "网", "宀": "宀", "夂": "夊",
    "⺈": "刀", "⺅": "人", "⻏": "邑", "𠆢": "人", "尣": "尢", "耂": "老",
}
canon = lambda c: VARIANT.get(c, c)

# ---- parse IDS ----
ids = {}
with open(f"{SRC}/ids.txt", encoding="utf-8") as f:
    for line in f:
        if line.startswith("#"):
            continue
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3:
            continue
        ch = parts[1]
        if len(ch) != 1:
            continue
        # prefer an unbracketed (generic) IDS; else the first
        cands = [p for p in parts[2:] if p and not p.startswith("^")] or parts[2:]
        pick = None
        for p in cands:
            body = re.sub(r"\[[A-Z]*\]$", "", p).strip("^$")
            if body and body != ch:
                pick = body
                break
        if pick:
            ids[ch] = pick

def _parts(s, ch):
    return [c for c in s if is_cjk(c) and c != ch and c != "？"]

def direct(ch):
    """one-level components. makemeahanzi is uniform 1-level but sometimes has
    ？ placeholders; fall back to CHISE ids.txt when that leaves <2 parts."""
    m = mmah.get(ch, "")
    parts = _parts(m, ch)
    if "？" in m or len(parts) < 2:
        alt = _parts(ids.get(ch, ""), ch)
        if len(alt) > len(parts):
            return alt
    return parts

def closure(ch, depth=0, seen=None):
    """recursive component set, canonicalised"""
    if seen is None:
        seen = set()
    if depth > 6 or ch in seen:
        return set()
    seen.add(ch)
    out = set()
    for c in direct(ch):
        out.add(canon(c))
        out.add(c)
        out |= closure(c, depth + 1, seen)
    return out

# ---- makemeahanzi etymology ----
etym, defin, radical, mmah = {}, {}, {}, {}
with open(f"{SRC}/dictionary.txt", encoding="utf-8") as f:
    for line in f:
        try:
            d = json.loads(line)
        except Exception:
            continue
        ch = d.get("character")
        if not ch or len(ch) != 1:
            continue
        if d.get("etymology"):
            etym[ch] = d["etymology"]
        if d.get("definition"):
            defin[ch] = d["definition"]
        if d.get("radical"):
            radical[ch] = d["radical"]
        if d.get("decomposition") and d["decomposition"] != "？":
            mmah[ch] = d["decomposition"]

chars = set(ids) | set(defin) | set(mmah)
out = {}
for ch in chars:
    if not is_cjk(ch):
        continue
    cl = closure(ch)
    out[ch] = {
        "ids": mmah.get(ch) or ids.get(ch, ""),
        "ids_chise": ids.get(ch, ""),
        "src": "makemeahanzi" if ch in mmah else "cjkvi",
        "direct": direct(ch),
        "closure": sorted(cl),
        "radical": radical.get(ch, ""),
        "etymology": etym.get(ch),
        "definition": defin.get(ch, ""),
    }

os.makedirs(f"{ROOT}/freq_data/ids", exist_ok=True)
dest = f"{ROOT}/freq_data/ids/decomp.json"
json.dump(out, open(dest, "w"), ensure_ascii=False)
print(f"wrote {dest}: {len(out)} characters")
print(f"  with IDS:        {sum(1 for v in out.values() if v['ids'])}")
print(f"  with etymology:  {sum(1 for v in out.values() if v['etymology'])}")
print(f"  from makemeahanzi: {sum(1 for v in out.values() if v['src']=='makemeahanzi')}")

for ch in "梯刮糕啤宾箱脚丢叔迟季裤":
    v = out.get(ch)
    if not v:
        print(f"  {ch}: MISSING"); continue
    e = v["etymology"] or {}
    hint = ""
    if e.get("type") == "pictophonetic":
        hint = f"  [semantic {e.get('semantic','?')} + phonetic {e.get('phonetic','?')}]"
    print(f"  {ch}  IDS={v['ids']:12} direct={''.join(v['direct'])}{hint}")
