#!/usr/bin/env python3
"""Pick the next N words to study from the web novel, ready for card generation.

Counted straight from the book text rather than from study_list_*.json: that list is
ranked over raw jieba tokens, so its head is character names (甜甜, 人鼠, 地狗) and
segmentation fragments (看着, 点点头, 一脸, 一把) — only 14 of its top 200 are actual
dictionary words. Ranking is by how often a word occurs in 十日终焉·囚笼, because a word
that recurs is one the reading itself will drill.

Filters, in the order they run:
  * must be a CC-CEDICT headword of 2+ characters — kills the fragments outright.
    Single characters are skipped on purpose: he reads nearly all of them already.
  * must not already have a note anywhere in the collection. Cards that exist stay
    exactly where they are — nothing is moved out of HSK or any other deck, and no
    duplicate is created. This only ever adds new notes.
  * must not be in the known set (Hanly export + page-reading calibration)
  * must not be tagged as a name by jieba in book context (nr/ns/nt/nz)
  * must occur at least MIN_N times

Reads only a COPY of the collection, so it is safe to run with the bot up. Character
names that are also real dictionary words (潇潇, 黑子) survive all of this — the
generation pass that follows is what drops them.

  novel_deck_build.py [--n 200] [--out freq_data/novel_deck_candidates.json]
"""
import argparse
import json
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path("/home/vincent/anki-headless")
EBOOKS = Path("/home/vincent/chinese-projects/ebooks")
BOOK = EBOOKS / "shiri_zhongyan_vol1.txt"
CEDICT = Path("/home/vincent/chinese-projects/dong-chinese/Resources/cedict_ts.u8")
HSK_TSV = Path("/home/vincent/chinese-projects/dong-chinese/server/app/data/hsk30.tsv")
HANLY = ROOT / "hanly_current.json"
MARKS = ROOT / "reading_marks.json"
HAN = re.compile(r"^[一-鿿]+$")
PROPER = ("nr", "ns", "nt", "nz")
MIN_N = 3          # a word seen once or twice in a 300k-character book is not worth a card
OVERSHOOT = 2.0    # hand this many times N to the generator; it drops names and duds


def cedict():
    """simplified -> (traditional, pinyin, first gloss)."""
    out = {}
    for line in CEDICT.open(encoding="utf-8"):
        if line.startswith("#"):
            continue
        m = re.match(r"(\S+)\s+(\S+)\s+\[([^\]]*)\]\s+/(.+)/", line)
        if m and m.group(2) not in out:
            out[m.group(2)] = (m.group(1), m.group(3), m.group(4).replace("/", "; ")[:200])
    return out


_TONES = {"a": "āáǎà", "e": "ēéěè", "i": "īíǐì", "o": "ōóǒò",
          "u": "ūúǔù", "ü": "ǖǘǚǜ"}


def pinyin_diacritic(numbered):
    """CEDICT stores tones as digits (xiang3 dong4); the existing cards use diacritics."""
    out = []
    for syl in numbered.split():
        m = re.match(r"^([a-zA-ZüÜ:]+)([1-5])$", syl)
        if not m:
            out.append(syl)
            continue
        body, tone = m.group(1).replace("u:", "ü").replace("U:", "Ü"), int(m.group(2))
        if tone == 5:
            out.append(body.lower())
            continue
        low = body.lower()
        # standard placement: a/e win, then the o of ou, else the last vowel
        idx = next((low.index(v) for v in ("a", "e") if v in low), None)
        if idx is None and "ou" in low:
            idx = low.index("o")
        if idx is None:
            idx = max((low.rindex(v) for v in "iouü" if v in low), default=None)
        if idx is None:
            out.append(low)
            continue
        out.append(low[:idx] + _TONES[low[idx]][tone - 1] + low[idx + 1:])
    return " ".join(out)


def hsk_levels():
    lv = {}
    for line in HSK_TSV.open(encoding="utf-8"):
        w, _, n = line.rstrip("\n").partition("\t")
        if n.isdigit():
            lv[w] = int(n)
    return lv


def collection_words():
    """Every Chinese word that already has a note, from a throwaway copy."""
    with tempfile.TemporaryDirectory() as td:
        cp = Path(td) / "col.anki2"
        shutil.copy(ROOT / "collection.anki2", cp)
        code = r'''
import json, sys
from anki.collection import Collection
c = Collection(sys.argv[1])
words = set()
for nid in c.find_notes(""):
    d = dict(c.get_note(nid).items())
    for f in ("Simplified", "Chinese", "Front", "Target Word", "Word"):
        v = d.get(f, "").strip()
        if v:
            words.add(v)
            break
c.close()
json.dump(sorted(words), open(sys.argv[2], "w"), ensure_ascii=False)
'''
        outp = Path(td) / "words.json"
        subprocess.run([str(ROOT / ".venv/bin/python"), "-c", code, str(cp), str(outp)],
                       check=True, capture_output=True)
        return set(json.loads(outp.read_text()))


def known_words():
    known = {w for w in json.loads(HANLY.read_text()).get("known", []) if HAN.match(w)}
    m = json.loads(MARKS.read_text())
    known |= set(m.get("presumed_known", []))
    known -= set(m.get("marked_not_solid", []))     # marked = explicitly not solid yet
    return known


WATERMARK = re.compile(r"(?:www\.|m\.)?hetushu(?:\.com)+\.?|_图_书|_书_|_图_")


def clean_sentence(s):
    """The scrape has the source site's watermark spliced into the prose — bare domains
    and _图_书 injected mid-sentence. Strip those, and the quote marks and newlines left
    hanging when a sentence starts mid-dialogue."""
    s = WATERMARK.sub("", s)
    s = re.sub(r"\s+", "", s)
    return s.strip("”“\"'」『』 \n\t")


def sample_sentences(text, words, per_word=2):
    """A couple of real sentences from the book for each word — card context and, for
    the screening pass, the evidence that tells a character name from a common noun."""
    hits = {w: [] for w in words}
    for sent in re.split(r"(?<=[。！？…])", text):
        sent = clean_sentence(sent)
        if not 8 <= len(sent) <= 60:
            continue
        for w in words:
            if len(hits[w]) < per_word and w in sent:
                hits[w].append(sent)
    return hits


def main():
    import jieba
    import jieba.posseg as pseg

    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--out", default=str(ROOT / "freq_data/novel_deck_candidates.json"))
    a = ap.parse_args()

    text = BOOK.read_text(encoding="utf-8", errors="ignore")
    ced, hsk = cedict(), hsk_levels()
    have, known = collection_words(), known_words()

    counts = Counter(w for w in jieba.cut(text) if len(w) >= 2 and HAN.match(w))
    propers = {w for w, f in pseg.cut(text) if f.startswith(PROPER)}

    skipped = Counter()
    ranked = []
    for w, n in counts.most_common():
        if n < MIN_N:
            break
        if w not in ced:
            skipped["not_a_dictionary_word"] += 1
        elif w in have:
            skipped["already_in_collection"] += 1
        elif w in known:
            skipped["known"] += 1
        elif w in propers:
            skipped["proper_noun"] += 1
        else:
            trad, pinyin, gloss = ced[w]
            ranked.append({"word": w, "n": n, "pinyin": pinyin, "traditional": trad,
                           "gloss": gloss, "hsk": hsk.get(w)})

    take = ranked[:int(a.n * OVERSHOOT)]
    sents = sample_sentences(text, [e["word"] for e in take])
    for e in take:
        e["book_sentences"] = sents[e["word"]]

    Path(a.out).write_text(json.dumps(
        {"book": "十日终焉·囚笼", "target": a.n, "pool": len(take),
         "skipped": dict(skipped), "words": take}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    print(f"{len(ranked)} eligible, pool of {len(take)} handed to the generator "
          f"for a target of {a.n} -> {a.out}")
    print("  skipped: " + ", ".join(f"{k} {v}" for k, v in skipped.most_common()))
    print(f"  occurrences: {take[0]['n']} (most) … {take[-1]['n']} (least in pool)")
    print("  " + " ".join(e["word"] for e in take[:50]) + " …")


if __name__ == "__main__":
    main()
