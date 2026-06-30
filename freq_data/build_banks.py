#!/usr/bin/env python3
"""Aggregate per-chunk lesson JSON (freq_data/lessons/<slug>__NN.json) into usable banks:
  banks/essays.md         — model-essay bank (study/imitate), grouped by book
  banks/grammar.md        — grammar-pattern bank (pattern + explanation + examples)
  banks/expressions.md    — high-value expressions/idioms for essays
  banks/takeaways.md      — distilled essay-writing lessons
  banks/lessons.json      — everything, structured, for programmatic use
Re-runnable as more chunks are synthesized."""
import os, json, re, glob, hashlib
from collections import defaultdict

ROOT = "/home/vincent/anki-headless"
LES = f"{ROOT}/freq_data/lessons"
BANKS = f"{ROOT}/freq_data/banks"
cls = {r["rel"]: r for r in json.load(open(f"{ROOT}/freq_data/ocr/_corpus_classification.json"))}
def _slug(rel):
    base = re.sub(r"[^\w]+", "_", os.path.splitext(rel)[0])[:60].strip("_")
    return f"{base}_{hashlib.sha1(rel.encode()).hexdigest()[:6]}"
slug2title = {_slug(rel): rel for rel in cls}

def book_of(chunk_slug):
    base = re.sub(r"__\d+$", "", chunk_slug)
    return slug2title.get(base, base)

def main():
    os.makedirs(BANKS, exist_ok=True)
    by_book = defaultdict(lambda: {"essays": [], "grammar": [], "expr": [], "takeaways": []})
    files = sorted(glob.glob(f"{LES}/*.json"))
    files = [f for f in files if not os.path.basename(f).startswith("_")]
    for f in files:
        cs = os.path.splitext(os.path.basename(f))[0]
        title = book_of(cs)
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        b = by_book[title]
        b["essays"] += d.get("model_essays", []) or []
        b["grammar"] += d.get("grammar_patterns", []) or []
        b["expr"] += d.get("expressions", []) or []
        b["takeaways"] += d.get("essay_takeaways", []) or []

    books = sorted(by_book)
    n_e = sum(len(by_book[b]["essays"]) for b in books)
    n_g = sum(len(by_book[b]["grammar"]) for b in books)
    n_x = sum(len(by_book[b]["expr"]) for b in books)

    # essays.md
    with open(f"{BANKS}/essays.md", "w", encoding="utf-8") as o:
        o.write(f"# Model-essay bank\n\n{n_e} passages from {len(books)} books — study these to imitate high-quality writing.\n\n")
        for b in books:
            es = by_book[b]["essays"]
            if not es: continue
            o.write(f"\n## {os.path.basename(b)}\n\n")
            for e in es:
                o.write(f"### {e.get('title','(untitled)')}  ·  _{e.get('genre','')}_\n\n")
                if e.get("summary"): o.write(f"*{e['summary']}*\n\n")
                if e.get("why_study"): o.write(f"**Why study:** {e['why_study']}\n\n")
                kd = e.get("key_devices") or []
                if kd: o.write("**Devices:** " + "; ".join(kd) + "\n\n")
                o.write(e.get("text","").strip() + "\n\n---\n\n")

    # grammar.md (dedup by pattern, keep first explanation, merge examples)
    seen = {}
    for b in books:
        for g in by_book[b]["grammar"]:
            k = (g.get("pattern") or "").strip()
            if not k: continue
            if k not in seen:
                seen[k] = {"explanation": g.get("explanation",""), "examples": list(g.get("examples") or []), "books": {os.path.basename(b)}}
            else:
                seen[k]["examples"] += g.get("examples") or []
                seen[k]["books"].add(os.path.basename(b))
    with open(f"{BANKS}/grammar.md", "w", encoding="utf-8") as o:
        o.write(f"# Grammar-pattern bank\n\n{len(seen)} distinct patterns.\n\n")
        for k in sorted(seen):
            v = seen[k]
            o.write(f"## {k}\n\n{v['explanation']}\n\n")
            for ex in v["examples"][:6]:
                o.write(f"- {ex}\n")
            o.write("\n")

    # expressions.md
    with open(f"{BANKS}/expressions.md", "w", encoding="utf-8") as o:
        o.write(f"# Essay expressions / idioms ({n_x})\n\n| 词语 | pinyin | meaning | register |\n|---|---|---|---|\n")
        seenx = set()
        for b in books:
            for x in by_book[b]["expr"]:
                z = (x.get("zh") or "").strip()
                if not z or z in seenx: continue
                seenx.add(z)
                o.write(f"| {z} | {x.get('pinyin','')} | {x.get('meaning','')} | {x.get('register','')} |\n")

    # takeaways.md
    with open(f"{BANKS}/takeaways.md", "w", encoding="utf-8") as o:
        o.write("# Essay-writing takeaways\n\n")
        for b in books:
            ts = by_book[b]["takeaways"]
            if not ts: continue
            o.write(f"## {os.path.basename(b)}\n\n")
            for t in ts: o.write(f"- {t}\n")
            o.write("\n")

    json.dump({b: by_book[b] for b in books}, open(f"{BANKS}/lessons.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"banks built from {len(files)} chunk files / {len(books)} books:")
    print(f"  essays={n_e}  grammar_patterns={len(seen)} (deduped from {n_g})  expressions={n_x}")
    print(f"  -> {BANKS}/essays.md, grammar.md, expressions.md, takeaways.md, lessons.json")

if __name__ == "__main__":
    main()
