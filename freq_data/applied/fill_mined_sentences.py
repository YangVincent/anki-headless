#!/usr/bin/env python3
"""Fill ONLY the empty sentence fields on mined cards. Two phases.

  generate (no --apply): call Claude, cache to /tmp/fill_mined_sentences.json
  apply    (--apply)   : write the cache onto the notes, via freq_data/anki_op.sh

WHY NOT improve_mined.py. That tool also regenerates `Meaning` and `Pinyin` for every
mined note. Vincent's gloss-style rule is a SHORT dictionary gloss, and 113 verbose
rewrites from July were reverted on 2026-08-01. This tool never touches Meaning or
Pinyin -- it writes a field only when that field is currently empty.

WHAT IT FILLS (measured over 515 mined cards):
   29  no SentenceSimplified at all  -> sentence + pinyin + translation
  223  sentence present, no translation and no SentencePinyin -> those two only

VALIDATION before anything is cached: a generated sentence must contain the target word,
must end in Chinese punctuation, and the word is bolded in code rather than trusted to
the model. A batch that fails validation is reported, not silently written.
"""
import argparse
import json
import re
import sys

ROOT = "/home/vincent/anki-headless"
CACHE = "/tmp/fill_mined_sentences.json"
MODEL = "claude-opus-5"
END = "。！？"

PROMPT = """You write example sentences for a Chinese vocabulary deck.

The learner is a heritage speaker: fluent in speech, reading at roughly HSK 4-5. He reads
novels (三体, 水浒传) and is working on formal written register.

For each item you get `word`, `gloss`, and possibly `sentence`.

If `sentence` is EMPTY, write one:
  - 12 to 22 Chinese characters, ending in 。 or ！ or ？
  - it must contain the `word` exactly as given, unmodified
  - it must show the word's normal collocation, not a bare definition restated
  - natural modern Mandarin; no names of real people; simplified characters

If `sentence` is PRESENT, keep it exactly as it is and do not rewrite it.

Return a JSON array. One object per item, with:
  "idx": the item's idx
  "sentence": the sentence (the one you wrote, or the one you were given, unchanged)
  "sentence_pinyin": tone-marked pinyin for that sentence. Capitalise the first letter,
      space between words, no punctuation. Use the reading that matches this sense.
  "sentence_en": a natural English translation of that sentence.

No prose, no markdown fence. Just the JSON array.

Items:
"""


def clean(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def load_notes():
    from anki.collection import Collection
    col = Collection(f"{ROOT}/collection.anki2")
    try:
        cv = col.models.by_name("ChineseVocabulary")
        F = {f["name"]: i for i, f in enumerate(cv["flds"])}
        out = []
        for nid in col.models.nids(cv["id"]):
            n = col.get_note(nid)
            if "mined" not in [t.lower() for t in n.tags]:
                continue
            sent = clean(n.fields[F["SentenceSimplified"]])
            need_sent = not sent
            need_tr = not clean(n.fields[F["SentenceMeaning"]])
            need_py = not clean(n.fields[F["SentencePinyin"]])
            if not (need_sent or need_tr or need_py):
                continue
            out.append(dict(nid=nid, word=n.fields[F["Simplified"]].strip(),
                            gloss=clean(n.fields[F["Meaning"]])[:80],
                            sentence=sent, need_sent=need_sent,
                            need_tr=need_tr, need_py=need_py))
        return out
    finally:
        col.close()


def generate(items, batch):
    import anthropic
    cfg = json.load(open(f"{ROOT}/.bot_config.json"))
    client = anthropic.Anthropic(api_key=cfg["anthropic_api_key"])
    results, bad = {}, []
    for i in range(0, len(items), batch):
        chunk = items[i:i + batch]
        payload = [dict(idx=j, word=b["word"], gloss=b["gloss"], sentence=b["sentence"])
                   for j, b in enumerate(chunk)]
        with client.messages.stream(
            model=MODEL, max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            messages=[{"role": "user",
                       "content": PROMPT + json.dumps(payload, ensure_ascii=False)}],
        ) as stream:
            resp = stream.get_final_message()
        txt = "".join(b.text for b in resp.content if b.type == "text")
        arr = json.loads(re.search(r"\[.*\]", txt, re.S).group(0))
        for o in arr:
            b = chunk[o["idx"]]
            s = (o.get("sentence") or "").strip()
            if b["word"] not in s:
                bad.append((b["word"], "sentence lacks the word", s)); continue
            if not s.endswith(tuple(END)):
                bad.append((b["word"], "no end punctuation", s)); continue
            if not b["need_sent"] and s != b["sentence"]:
                bad.append((b["word"], "rewrote an existing sentence", s)); continue
            results[str(b["nid"])] = dict(
                word=b["word"], sentence=s,
                bolded=s.replace(b["word"], f"<b>{b['word']}</b>", 1),
                pinyin=(o.get("sentence_pinyin") or "").strip(),
                en=(o.get("sentence_en") or "").strip(),
                need_sent=b["need_sent"], need_tr=b["need_tr"], need_py=b["need_py"])
        print(f"  batch {i//batch + 1}/{(len(items)+batch-1)//batch}: "
              f"{len(arr)} back, {len(results)} good so far")
    return results, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=12)
    ap.add_argument("--limit", type=int, help="only process the first N (a trial run)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not args.apply:
        items = load_notes()
        if args.limit:
            items = items[:args.limit]
        n_s = sum(1 for i in items if i["need_sent"])
        print(f"mined notes needing work: {len(items)}  "
              f"({n_s} need a sentence, {len(items)-n_s} need translation/pinyin only)")
        res, bad = generate(items, args.batch)
        json.dump(res, open(CACHE, "w"), ensure_ascii=False, indent=1)
        print(f"\ncached {len(res)} -> {CACHE}")
        if bad:
            print(f"\nREJECTED {len(bad)} (not cached):")
            for w, why, s in bad[:12]:
                print(f"   {w}: {why} -- {s[:50]}")
        print("\nsamples:")
        for nid in list(res)[:8]:
            r = res[nid]
            print(f"   {r['word']}: {r['sentence']}")
            print(f"      {r['pinyin'][:60]}")
            print(f"      {r['en'][:60]}")
        return

    from anki.collection import Collection
    res = json.load(open(CACHE))
    col = Collection(f"{ROOT}/collection.anki2")
    try:
        cv = col.models.by_name("ChineseVocabulary")
        F = {f["name"]: i for i, f in enumerate(cv["flds"])}
        wrote = 0
        for nid, r in res.items():
            n = col.get_note(int(nid))
            assert n.fields[F["Simplified"]].strip() == r["word"], nid
            touched = False
            # ONLY ever fill an empty field.
            if r["need_sent"] and not clean(n.fields[F["SentenceSimplified"]]):
                n.fields[F["SentenceSimplified"]] = r["bolded"]; touched = True
            if r["need_py"] and not clean(n.fields[F["SentencePinyin"]]) and r["pinyin"]:
                n.fields[F["SentencePinyin"]] = r["pinyin"]; touched = True
            if r["need_tr"] and not clean(n.fields[F["SentenceMeaning"]]) and r["en"]:
                n.fields[F["SentenceMeaning"]] = r["en"]; touched = True
            if touched:
                col.update_note(n); wrote += 1
        print(f"wrote {wrote} note(s)")
        left = 0
        for nid, r in res.items():
            n = col.get_note(int(nid))
            if not clean(n.fields[F["SentenceSimplified"]]): left += 1
        print(f"verify: cached notes still without a sentence = {left}")
        assert left == 0
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
