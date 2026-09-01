#!/usr/bin/env python3
"""Score a Chinese text against what the Anki collection says the user knows.

WHY NOT JUST FREQUENCY. difficulty_report.py ranks a text on the wordfreq Zipf scale,
calibrated by the words the user taps in the reader. This module asks a different
question: which words in this text does his own collection say he has learned?

WHAT THE COLLECTION CAN AND CANNOT SAY. Measured against wordfreq's rank order, for
multi-character words:

    rank 1-300     97.3% known      97.3% in the collection
    rank 300-1000  84.3% known      95.7% in the collection
    rank 1000-3000 53.8% known      89.4% in the collection

So the collection covers common words, and the known share falls away exactly where the
learning frontier is. That is what makes it usable. Two limits follow from the same data:

  * Single characters are out of scope. 的, 是, 了, 我 and 他 are in no deck, because the
    user is a heritage speaker and never studied them. A single-character word therefore
    reads as "unknown" for a reason that has nothing to do with the text. Only words of
    two characters or more are scored, which is also what difficulty_report.py counts.

  * A word absent from the collection is unmeasured, NOT unknown. The queue is frequency
    ordered, so an absent word is usually a rare one, but the collection does not say so.
    The three buckets stay separate in the output for that reason.

The buckets, per content-word token:

    known    a card exists and is not new — mature or in learning
    queued   a card exists and is still new — on his list, not yet learned
    absent   no card at all

`coverage` is the known share. Reading research puts comfortable extensive reading near
95% and fluent reading near 98%, which is the scale to read it on.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anki_cache as ac  # noqa: E402

HAN = re.compile(r"[一-鿿]")
#: A rough traditional/simplified probe. Cheap, and it only has to decide whether the
#: converter is worth running; the converter itself does the real work.
_TRAD = "這說個時後們來對開學國會發現愛覺當實過樂點頭萬爾與從麼聲衛遠邊興"
_SIMP = "这说个时后们来对开学国会发现爱觉当实过乐点头万尔与从么声卫远边兴"
PROPER_FLAGS = ("nr", "ns", "nt", "nz")
#: A word absent from the collection but this common is one a heritage speaker reads
#: without help. Reported separately so the assumption stays visible; it is never folded
#: into `known`.
COMMON_ZIPF = 5.0


def looks_traditional(text):
    return sum(text.count(c) for c in _TRAD) > sum(text.count(c) for c in _SIMP)


def to_simplified(text, force=False):
    """Convert traditional text to simplified, so it can meet a simplified collection.

    Every card in the collection stores simplified, so a traditional source scores as
    almost entirely unknown: 十年 in the Cold Window guide read 57% new words and 33%
    new characters until this ran. Simplified input is left alone.

    PASS force=True FOR ANY SHORT STRING. looks_traditional() counts characters from a
    fixed marker set, which a long chapter always contains and a one-line fragment may
    not. A 30-character preview line of 十年 kept its 見 while the chapter it came from
    became 见, and the two then failed an equality check that should have passed.
    """
    if not force and not looks_traditional(text):
        return text, False
    import opencc
    out = opencc.OpenCC("t2s").convert(text)
    return out, out != text


#: Words confirmed known by hand, with no studied card behind them. Lives beside the
#: collection, NOT in anki_cache.known_words(): that function is the dong contract for
#: "a card exists and is not new", and tests/test_cache.py asserts it reproduces the old
#: backfill exactly. Knowledge without a card is a different fact and gets its own file.
KNOWN_EXTRA = Path(__file__).resolve().parent.parent / "known_extra.json"


@dataclass
class Knowledge:
    known: dict          # word -> "mature" | "learning" | "confirmed"
    queued: set          # word -> a card exists, still new
    chars: set           # every character inside a known word
    generated_at: int
    confirmed: set = None   # the subset confirmed by hand, with no card behind it

    @property
    def in_collection(self):
        return set(self.known) | self.queued


def load(con=None):
    """Read the collection's read cache. Never opens the Anki library, never writes."""
    con = con or ac.connect_ro()
    meta = ac.read_meta(con)
    known = ac.known_words(con)
    queued = {r["simplified"] for r in con.execute(
        "select simplified from words where role != ? and blocked is null and status = 'new'",
        (ac.decks.ARCHIVE,)) if ac._is_plain_word(r["simplified"])}
    queued -= set(known)
    extra = load_known_extra()
    for word in extra:
        known.setdefault(word, "confirmed")
    queued -= set(extra)
    return Knowledge(known=known, queued=queued, confirmed=set(extra),
                     chars={c for w in known for c in w},
                     generated_at=meta["generated_at"])


def load_known_extra(path=None):
    """{word: record} from known_extra.json, or {} when the file is absent."""
    path = Path(path or KNOWN_EXTRA)
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {e["word"]: e for e in doc.get("entries", [])}


def cover(text, k, min_len=2, drop=()):
    """Bucket every content-word token of `text` against the collection.

    `drop` removes tokens before scoring — pass the book's character names, which
    jieba's own tagger misses often enough to matter. See name_filter.py.
    """
    import jieba.posseg as pseg
    from wordfreq import zipf_frequency

    drop = set(drop)
    tokens = [t for t, flag in pseg.cut(text)
              if len(t) >= min_len and HAN.search(t)
              and not flag.startswith(PROPER_FLAGS) and t not in drop]
    counts = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    total = len(tokens) or 1

    known = queued = absent = absent_common = 0
    opaque = transparent = 0
    unknown_types = {}
    for w, n in counts.items():
        if w in k.known:
            known += n
            continue
        unknown_types[w] = n
        if w in k.queued:
            queued += n
        else:
            absent += n
            if zipf_frequency(w, "zh") >= COMMON_ZIPF:
                absent_common += n
        # A compound built only from characters he has already met inside a word he
        # knows is guessable; 小猪 and 母鹅 are the shape of it. One unmet character
        # makes the word opaque instead. This is the split that matters to a heritage
        # speaker, whose character stock runs far ahead of his studied word list.
        if all(c in k.chars for c in w if HAN.match(c)):
            transparent += n
        else:
            opaque += n

    han = HAN.findall(text)
    unseen_chars = {c for c in set(han) if c not in k.chars}
    unseen_char_tok = sum(1 for c in han if c not in k.chars)

    return {
        "tokens": total, "types": len(counts),
        "coverage": 100 * known / total,
        "queued_pct": 100 * queued / total,
        "absent_pct": 100 * absent / total,
        "absent_common_pct": 100 * absent_common / total,
        "unknown_pct": 100 * (queued + absent) / total,
        "opaque_pct": 100 * opaque / total,
        "transparent_pct": 100 * transparent / total,
        "chars": len(han), "unseen_chars": len(unseen_chars),
        "unseen_char_pct": 100 * unseen_char_tok / max(len(han), 1),
        "top_unknown": sorted(unknown_types.items(), key=lambda x: -x[1])[:15],
    }


def band(opaque_pct, anchor):
    """Label one text against a reference text scored in the same run.

    The absolute percentages here run high, because the known-character set comes from
    the 2,894 studied words and holds 1,239 characters — far fewer than a heritage
    speaker reads. That offset applies to every text equally, so the comparison holds
    even where the absolute number does not. Pass the anchor; never hard-code one.
    """
    ratio = opaque_pct / anchor if anchor else 1.0
    return ("much easier" if ratio < 0.75 else
            "easier" if ratio < 0.92 else
            "about the same" if ratio < 1.08 else
            "harder" if ratio < 1.35 else
            "much harder")
