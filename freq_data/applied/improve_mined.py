#!/usr/bin/env python3
"""Improve all mined cards' content. Two phases:
  generate (no --apply): read mined notes, call Claude in batches to produce correct
    sense-matched pinyin, a clean fuller meaning, the sentence's pinyin, and an English
    translation; validate pinyin against CC-CEDICT; cache to /tmp/improve_mined.json.
  apply (--apply): write the cached fields onto the notes (run via anki_op.sh).
Reuses the bot's Anthropic key + char_gen's model."""
import sys, json, re, time
from anki.collection import Collection
ROOT = "/home/vincent/anki-headless"
APPLY = "--apply" in sys.argv
CACHE = "/tmp/improve_mined.json"
MODEL = "claude-sonnet-4-5-20250929"
def clean(s): return re.sub(r'<[^>]+>', '', s or '').strip()

# CC-CEDICT readings per simplified word (toneless bases) for pinyin sanity-check
def load_cedict_bases():
    bases = {}
    for line in open("/home/vincent/chinese-projects/dong-chinese/Resources/cedict_ts.u8", encoding="utf-8"):
        m = re.match(r'\S+\s+(\S+)\s+\[([^\]]*)\]', line)
        if not m: continue
        simp, py = m.group(1), m.group(2)
        base = re.sub(r'[0-9 ]', '', py).lower()
        bases.setdefault(simp, set()).add(base)
    return bases

def get_notes():
    col = None
    for _ in range(30):
        try: col = Collection(f"{ROOT}/collection.anki2"); break
        except Exception: time.sleep(2)
    if col is None: print("collection locked"); sys.exit(1)
    try:
        cv = col.models.by_name("ChineseVocabulary"); SEP = chr(31)
        fi = {f['name']: i for i, f in enumerate(cv['flds'])}
        vd = col.decks.id_for_name("Vocab"); md = col.decks.id_for_name("Mined")
        nids = col.db.list("SELECT DISTINCT n.id FROM cards c JOIN notes n ON c.nid=n.id "
                           "WHERE c.ord=0 AND n.mid=? AND n.tags LIKE '%mined%' AND c.did IN (?,?)",
                           cv['id'], vd, md)
        out = []
        for nid in nids:
            n = col.get_note(nid)
            out.append(dict(nid=nid, word=clean(n.fields[fi['Simplified']]),
                            gloss=clean(n.fields[fi['Meaning']]), sentence=clean(n.fields[fi['SentenceSimplified']])))
        return out
    finally:
        col.close()

PROMPT = """You are improving Chinese vocabulary flashcards for an advanced learner. For EACH item, given the word, a rough gloss, and an example sentence, return corrected fields. Crucially, the PINYIN must match the pronunciation of the word as used in that sentence/sense (e.g. 中 meaning "to hit" is "zhòng" not "zhōng"; 还 meaning "to return" is "huán" not "hái").

Return ONLY a JSON array; one object per item with keys:
- "idx": the item's idx
- "pinyin": Hanyu Pinyin WITH TONE MARKS for the word, in the sentence's sense (lowercase)
- "meaning": a concise, clear English definition (note the sense used; keep it short)
- "sentence_pinyin": tone-marked pinyin for the whole sentence (Capitalize first letter, spaces between words, omit punctuation)
- "sentence_en": a natural English translation of the sentence
No prose, no markdown — just the JSON array.

Items:
"""

if not APPLY:
    import anthropic
    cfg = json.load(open(f"{ROOT}/.bot_config.json"))
    client = anthropic.Anthropic(api_key=cfg["anthropic_api_key"])
    items = get_notes()
    bases = load_cedict_bases()
    print(f"mined notes to improve: {len(items)}")
    results = {}; flagged = []
    B = 16
    for i in range(0, len(items), B):
        batch = items[i:i + B]
        payload = [dict(idx=j, word=b['word'], gloss=b['gloss'], sentence=b['sentence']) for j, b in enumerate(batch)]
        resp = client.messages.create(model=MODEL, max_tokens=4096,
                                      messages=[{"role": "user", "content": PROMPT + json.dumps(payload, ensure_ascii=False)}])
        txt = resp.content[0].text
        arr = json.loads(re.search(r'\[.*\]', txt, re.S).group(0))
        for o in arr:
            b = batch[o['idx']]; w = b['word']
            py = (o.get('pinyin') or '').strip()
            pbase = re.sub(r'[^a-zü]', '', py.lower())
            ok = (w not in bases) or any(pbase == bb for bb in bases[w]) or pbase in {x for bb in bases[w] for x in [bb]}
            if w in bases and not any(pbase == bb for bb in bases[w]):
                flagged.append((w, py, sorted(bases[w])))
            results[str(b['nid'])] = dict(word=w, pinyin=py, meaning=(o.get('meaning') or '').strip(),
                                          sentence_pinyin=(o.get('sentence_pinyin') or '').strip(),
                                          sentence_en=(o.get('sentence_en') or '').strip())
        print(f"  batch {i//B + 1}/{(len(items)+B-1)//B}: {len(arr)} done")
    json.dump(results, open(CACHE, "w"), ensure_ascii=False, indent=1)
    print(f"\nsaved {len(results)} -> {CACHE}")
    print("samples:")
    for nid in list(results)[:10]:
        r = results[nid]; print(f"  {r['word']}: {r['pinyin']}  | {r['meaning']}  | {r['sentence_en'][:42]}")
    if flagged:
        print(f"\npinyin not matching any CC-CEDICT reading ({len(flagged)}) — review:")
        for w, py, bb in flagged[:20]: print(f"   {w}: model={py!r} cedict={bb}")
else:
    results = json.load(open(CACHE))
    col = Collection(f"{ROOT}/collection.anki2")
    try:
        cv = col.models.by_name("ChineseVocabulary"); SEP = chr(31)
        fi = {f['name']: i for i, f in enumerate(cv['flds'])}
        applied = 0
        for nid, r in results.items():
            try: n = col.get_note(int(nid))
            except Exception: continue
            if r.get('pinyin'): n.fields[fi['Pinyin']] = r['pinyin']
            if r.get('meaning'): n.fields[fi['Meaning']] = r['meaning']
            if r.get('sentence_pinyin'): n.fields[fi['SentencePinyin']] = r['sentence_pinyin']
            if r.get('sentence_en'): n.fields[fi['SentenceMeaning']] = r['sentence_en']
            col.update_note(n); applied += 1
        print(f"APPLIED improvements to {applied} notes")
    finally:
        col.close()
