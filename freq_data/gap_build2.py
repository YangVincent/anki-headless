#!/usr/bin/env python3
"""Characters that appear in HSK 1-6 deck words but are NOT in Hanly.

Differs from gap_build.py in three ways:
  * reads the current Hanly dump (all chars treated as known)
  * no frequency threshold. Every HSK 1-6 word counts: if it's in HSK, it's
    worth knowing. (The old Zipf>4.5 head dropped 55.6% of the deck.)
  * reports where each char's card currently lives, so archived-but-needed
    chars are visible.

Read-only on the collection. Writes freq_data/chars/gap_chars_v2.json
Usage: gap_build2.py [--hanly hanly_july_8_2026.json] [--new-only]
"""
import sqlite3, json, collections, re, sys, os
from pypinyin import pinyin, Style

ROOT = "/home/vincent/anki-headless"
HSK_DID = 1781536737704
CEDICT = "/home/vincent/chinese-projects/dong-chinese/Resources/cedict_ts.u8"

arg = lambda f, d: (sys.argv[sys.argv.index(f) + 1] if f in sys.argv else d)
HANLY_FILE = arg("--hanly", f"{ROOT}/hanly_july_8_2026.json")
NEW_ONLY = "--new-only" in sys.argv

# --- collection: snapshot via backup API (safe against the live WAL) ---
tmp = "/tmp/col_gap2_read.anki2"
if os.path.exists(tmp):
    os.remove(tmp)
src = sqlite3.connect(f"file:{ROOT}/collection.anki2?mode=ro", uri=True)
dst = sqlite3.connect(tmp)
src.backup(dst)
dst.close(); src.close()

c = sqlite3.connect(tmp)
c.create_collation("unicase", lambda a, b: (a.lower() > b.lower()) - (a.lower() < b.lower()))
strip_html = lambda h: re.sub(r"<[^>]+>", "", h or "").strip()

# HSK deck words + whether still unlearned
word_queues = collections.defaultdict(set)
for flds, q in c.execute(
    """select n.flds, cd.queue from cards cd
       join notes n on n.id=cd.nid join notetypes nt on nt.id=n.mid
       where cd.did=? and nt.name='ChineseVocabulary'""", (HSK_DID,)):
    w = strip_html(flds.split(chr(31))[0])
    if w:
        word_queues[w].add(q)

words = [w for w in word_queues if not NEW_ONLY or 0 in word_queues[w]]
is_new = lambda w: 0 in word_queues[w]

# Hanly: every character it has introduced, assumed learned.
raw = json.load(open(HANLY_FILE))
hanly = {k for k in raw if len(k) == 1}
hanly |= {k.split("_", 1)[0] for k in raw if "_" in k and len(k.split("_", 1)[0]) == 1}

# where does each character's card currently live?
deck_name = {i: n.replace(chr(31), "::") for i, n in c.execute("select id,name from decks")}
QLBL = {-1: "suspended", 0: "new", 1: "learning", 2: "review", 3: "daylearn"}
char_status = {}
for flds, did, q in c.execute(
    """select n.flds, cd.did, cd.queue from cards cd
       join notes n on n.id=cd.nid join notetypes nt on nt.id=n.mid
       where nt.name='ChineseCharacters'"""):
    ch = strip_html(flds.split(chr(31))[0])
    if len(ch) != 1:
        continue
    cur = (deck_name.get(did, "?"), QLBL.get(q, q))
    # prefer an active card over a suspended one when a char has several
    if ch not in char_status or cur[1] != "suspended":
        char_status[ch] = cur

# CEDICT single-char glosses
ced_raw = collections.defaultdict(list)
with open(CEDICT) as f:
    for line in f:
        if line.startswith("#"):
            continue
        m = re.match(r"(\S+) (\S+) \[([^\]]*)\] /(.+)/", line)
        if m and len(m.group(2)) == 1:
            ced_raw[m.group(2)].append((m.group(1), [s for s in m.group(4).split("/") if s]))

def best_gloss(ch):
    if ch not in ced_raw:
        return (ch, "")
    trad = ced_raw[ch][0][0]
    senses = [s for _, ss in ced_raw[ch] for s in ss]
    skip = lambda s: bool(re.match(r"(surname |variant of|old variant|abbr\.? for|see )", s, re.I))
    good = [s for s in senses if not skip(s)] or senses
    seen, uniq = set(), []
    for s in good:
        if s not in seen:
            seen.add(s); uniq.append(s)
    return (trad, "; ".join(uniq)[:80])

han_chars = lambda w: [ch for ch in w if "一" <= ch <= "鿿"]

words_new = collections.Counter()  # unlearned words containing this char
words_all = collections.Counter()
examples = collections.defaultdict(list)

for w in words:
    for ch in set(han_chars(w)):
        if ch in hanly:
            continue
        words_all[ch] += 1
        if is_new(w):
            words_new[ch] += 1
        if len(examples[ch]) < 6:
            examples[ch].append(w)

# leverage: unlock the most *unlearned* words first, then most total
head = sorted(words_all, key=lambda ch: (-words_new[ch], -words_all[ch], ch))

out = []
for rank, ch in enumerate(head):
    trad, gloss = best_gloss(ch)
    deck, state = char_status.get(ch, ("(no card)", "-"))
    out.append({
        "rank": rank, "char": ch, "pinyin": pinyin(ch, style=Style.TONE)[0][0],
        "meaning": gloss[:80], "trad": trad,
        "words_new": words_new[ch], "words_all": words_all[ch],
        "deck": deck, "card_state": state,
        "examples": examples[ch],
    })

os.makedirs(f"{ROOT}/freq_data/chars", exist_ok=True)
dest = f"{ROOT}/freq_data/chars/gap_chars_v2.json"
json.dump(out, open(dest, "w"), ensure_ascii=False, indent=1)

src_desc = "new HSK words only" if NEW_ONLY else "all HSK 1-6 deck words"
print(f"hanly: {HANLY_FILE.split('/')[-1]} -> {len(hanly)} chars assumed known")
print(f"source: {src_desc} -> {len(words)} words considered (no frequency filter)")
print(f"gap chars not in Hanly: {len(out)}\n")

by_state = collections.Counter((o["deck"], o["card_state"]) for o in out)
print("where their cards live now:")
for (d, s), n in by_state.most_common():
    print(f"  {d:35} {s:10} {n:5}")

queued = sum(1 for o in out if o["card_state"] in ("new", "learning", "review"))
print(f"\nactively queued: {queued}   not queued: {len(out)-queued}")

print("\ntop 20 by unlearned-word leverage:")
for o in out[:20]:
    print(f"  {o['rank']:>3} {o['char']} {o['pinyin']:<7} new={o['words_new']:<3} all={o['words_all']:<3} "
          f"{o['card_state']:<9} {' '.join(o['examples'][:4])}")
print(f"\nwrote {dest}")
