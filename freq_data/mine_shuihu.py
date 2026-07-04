#!/usr/bin/env python3
"""Mine 水浒传 (Rainbow Bridge L5) glossed vocabulary into the Vocab deck.
For every book-glossed word the user doesn't already know:
  - NOT in deck  -> create a ChineseVocabulary note (book gloss+sentence, recomputed
                    pinyin, opencc Traditional, derived bold/cloze/sentence-pinyin),
                    forward card front-of-queue, reverse suspended, cloze -> Vocab Cloze suspended.
  - in deck but still NEW (type 0) -> reposition front-of-queue + tag (no duplicate).
  - in deck and already studied -> skip.
Tags: mined, shuihu. Dry-run unless --apply. Run via anki_op.sh."""
import sys, re, glob
import fitz, jieba
from pypinyin import pinyin as pyin, Style
import opencc
from anki.collection import Collection
APPLY = "--apply" in sys.argv
ROOT = "/home/vincent/anki-headless"
HANs = '一-鿿'; HAN = re.compile(f'[{HANs}]')
s2t = opencc.OpenCC('s2t')

def clean(s): return re.sub(r'<[^>]+>', '', s or '').strip()
def wpy(w):  # word pinyin, tone marks
    return ''.join(t[0] for t in pyin(w, style=Style.TONE))
def mkpy(s):  # sentence pinyin, jieba word-grouped
    parts = []
    for w in jieba.cut(s):
        if HAN.search(w): parts.append(''.join(t[0] for t in pyin(w, style=Style.TONE)))
        elif w.strip(): parts.append(w)
    out = ''
    for p in parts:
        if not out: out = p
        elif re.match(rf'^[A-Za-z0-9{HANs}]', p): out += ' ' + p
        else: out += p
    return (out[:1].upper() + out[1:]).strip()
def bold(s, w): return s.replace(w, f"<b>{w}</b>", 1) if w in s else s
def blank(s, w): return s.replace(w, "[ ]", 1) if w in s else s

# --- parse book glosses: word -> (pinyin_unused, english, sentence) ---
f = [x for x in glob.glob(f"{ROOT}/freq_data/books/*.pdf") if "Three Kingdoms" in x][0]
d = fitz.open(f); full = "\n".join(d[i].get_text() for i in range(d.page_count))
starts = list(re.finditer(rf'(?m)^[a-z]\t\s*([{HANs}]+?)\s*\(([^)]*)\)', full))
G = {}
for i, m in enumerate(starts):
    w = m.group(1)
    if not (1 <= len(w) <= 4) or w in G: continue
    chunk = full[m.end(): (starts[i+1].start() if i+1 < len(starts) else m.end()+260)]
    em = re.match(r'\s*(.*?)\s*e\.g\.,', chunk, re.S)
    eng = re.sub(r'\s+', ' ', em.group(1)).strip() if em else ''
    sm = re.search(r'e\.g\.,\s*(.*?[。！？])', chunk, re.S)
    sent = re.sub(r'\s+', '', sm.group(1)) if sm else ''
    if eng: G[w] = (eng, sent)
print(f"book-glossed words parsed: {len(G)}")

col = Collection(f"{ROOT}/collection.anki2")
try:
    cv = col.models.by_name("ChineseVocabulary"); SEP = chr(31)
    fi = {fl['name']: i for i, fl in enumerate(cv['flds'])}
    vocab_did = col.decks.id("Vocab")
    cloze_did = col.decks.id("Vocab Cloze")
    cloze_ord = next(t['ord'] for t in cv['tmpls'] if t['name'] == "Cloze-Recall")

    # deck status per word
    in_deck = {}   # word -> (nid, forward_type)
    for nid, flds in col.db.all("SELECT n.id,n.flds FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND c.ord=0 AND n.mid=?", vocab_did, cv['id']):
        w = clean(flds.split(SEP)[fi['Simplified']])
        t = col.db.scalar("SELECT type FROM cards WHERE nid=? AND ord=0", nid)
        in_deck[w] = (nid, t)

    to_create = []; to_reposition = []; skip_known = []
    for w, (eng, sent) in G.items():
        if w in in_deck:
            nid, t = in_deck[w]
            (to_reposition if t == 0 else skip_known).append(w)
        else:
            to_create.append(w)
    print(f"  NEW notes to create:        {len(to_create)}")
    print(f"  in-deck, reposition to front:{len(to_reposition)}")
    print(f"  in-deck, already studied(skip):{len(skip_known)}")

    if not APPLY:
        print("\nsample new cards:")
        for w in to_create[:8]:
            eng, sent = G[w]
            print(f"  {w} [{wpy(w)}] {eng[:30]} | {bold(sent,w)}")
        print("DRY-RUN — rerun with --apply")
        sys.exit(0)

    # ---- create new notes ----
    new_fwd = []; new_cloze = []; new_rev = []
    for w in to_create:
        eng, sent = G[w]
        tw = s2t.convert(w); tsent = s2t.convert(sent)
        note = col.new_note(cv)
        note.fields[fi['Simplified']] = w
        note.fields[fi['Traditional']] = tw
        note.fields[fi['Pinyin']] = wpy(w)
        note.fields[fi['Meaning']] = eng
        note.fields[fi['CustomFreq']] = "mined · 水浒传"
        if sent:
            note.fields[fi['SentenceSimplified']] = bold(sent, w)
            note.fields[fi['SentenceTraditional']] = bold(tsent, tw)
            note.fields[fi['SentenceSimplifiedCloze']] = blank(sent, w)
            note.fields[fi['SentenceTraditionalCloze']] = blank(tsent, tw)
            note.fields[fi['SentencePinyin']] = mkpy(sent)
        note.tags = ["mined", "shuihu"]
        col.add_note(note, vocab_did)
        for c in note.cards():
            if c.ord == 0: new_fwd.append(c.id)
            elif c.ord == 1: new_rev.append(c.id)
            elif c.ord == cloze_ord: new_cloze.append(c.id)

    # route the generated cards
    if new_rev: col.sched.suspend_cards(new_rev)
    if new_cloze:
        col.set_deck(new_cloze, cloze_did)
        col.sched.suspend_cards(new_cloze)

    # ---- reposition existing in-deck new cards + tag ----
    repo_fwd = []
    for w in to_reposition:
        nid, _ = in_deck[w]
        note = col.get_note(nid)
        for tg in ("mined", "shuihu"):
            if tg not in [t.lower() for t in note.tags]: note.tags.append(tg)
        col.update_note(note)
        cid = col.db.scalar("SELECT id FROM cards WHERE nid=? AND ord=0", nid)
        repo_fwd.append(cid)

    # ---- front-of-queue all forward cards (new + repositioned) ----
    fwd_all = new_fwd + repo_fwd
    if fwd_all:
        col.sched.unsuspend_cards(fwd_all)
        col.set_deck(fwd_all, vocab_did)
        min_due = col.db.scalar("SELECT MIN(due) FROM cards WHERE did=? AND type=0 AND ord=0", vocab_did)
        nd = min(min_due if min_due is not None else 1, 1) - 1
        for cid in fwd_all:
            c = col.get_card(cid); c.due = nd; col.update_card(c); nd -= 1

    print(f"APPLIED: created {len(new_fwd)} new notes, repositioned {len(repo_fwd)}, "
          f"cloze->VocabCloze {len(new_cloze)} (suspended), reverse suspended {len(new_rev)}")
    print(f"  all {len(fwd_all)} forward cards placed front-of-queue (tagged mined+shuihu)")
finally:
    col.close()
