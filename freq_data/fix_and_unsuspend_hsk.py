#!/usr/bin/env python3
"""Repair + unsuspend the 511 suspended HSK 3.0 word cards (the 2026-07-08 bulk suspend).

Three independent passes, all inside one stopped-bot window (anki_op.sh), each verified
before exit:

  1. GLOSS   — 25 notes whose Meaning/Pinyin came from CC-CEDICT's *proper-noun* entry
               (烈日 = "Liege, town in Belgium"). `replace` takes the common-word entry's
               pinyin+defs from chinese-dict (:3020); `pinyin_only` keeps the Meaning and
               just de-capitalizes the pinyin. Driven by freq_data/gen_fix/glosses.json.
  2. SENTENCE— 64 notes whose SentenceSimplified is a Naruto-subtitle fragment with no
               pinyin/translation/traditional/cloze. Sentences authored in
               freq_data/gen_fix/sentences.json; traditional via opencc, sentence pinyin
               via pypinyin+jieba, bold + [ ] cloze derived here (same rules as
               freq_data/apply_sentences.py). SentenceAudio is left empty (TTS is a
               separate pass, per freq_data/README.md).
  3. UNSUSPEND+REPOSITION — unsuspend every target ord=0 card, then splice the new ones
               back into their deck's new queue at the position implied by the queue's
               existing sort key (HSK: level asc, zipf desc; HSK7-9: zipf desc).

               The queue is NOT globally re-sorted: 867 hand-placed ChineseCharacters gap
               cards are interleaved in HSK's new queue (place_gap_chars.py), and
               quality/resort_hsk_by_level.py would scramble them. Instead every new ord=0
               card in the deck is repositioned in its CURRENT relative order with the
               targets spliced in, so non-target cards keep their neighbours exactly.

Deliberately NOT touched: spaced pinyin ("fā yuán dì") and "1." numbered glosses — those
are collection-wide conventions (54% / 37% of ACTIVE cards have them too), not defects.
Missing Audio likewise (232/600 active cards lack it).

Usage:  bash freq_data/anki_op.sh fix-hsk freq_data/fix_and_unsuspend_hsk.py --apply
        (add --db PATH to run against a scratch copy; default is the live collection)
"""
import sys, json, re, argparse, urllib.request, urllib.parse, collections

from anki.collection import Collection
from wordfreq import zipf_frequency
from opencc import OpenCC
from pypinyin import pinyin, Style
import jieba

ROOT = "/home/vincent/anki-headless"
SEP = chr(31)
DICT_URL = "http://127.0.0.1:3020/api/search?q="
TO_TRAD = OpenCC("s2t").convert


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def sent_pinyin(sent):
    """Sentence pinyin with tone marks: segment with jieba, keep punctuation, capitalize."""
    out = []
    for tok in jieba.cut(sent):
        if re.search(r"[一-鿿]", tok):
            out.append("".join(p[0] for p in pinyin(tok, style=Style.TONE)))
        elif tok.strip():
            out.append({"，": ",", "。": ".", "？": "?", "！": "!", "、": ",",
                        "“": '"', "”": '"', "：": ":", "；": ";"}.get(tok, tok))
    s = " ".join(out)
    s = re.sub(r"\s+([,.?!;:])", r"\1", s)
    return s[:1].upper() + s[1:] if s else s


def dict_entries(word):
    with urllib.request.urlopen(DICT_URL + urllib.parse.quote(word), timeout=5) as r:
        return [e for e in json.load(r)["results"] if e["simplified"] == word]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    APPLY = args.apply

    hsk_vocab = json.load(open(f"{ROOT}/freq_data/hsk3_vocab.json"))
    level_of = {w["word"]: w["level"] for w in hsk_vocab}
    sentences = json.load(open(f"{ROOT}/freq_data/gen_fix/sentences.json"))
    gfix = json.load(open(f"{ROOT}/freq_data/gen_fix/glosses.json"))

    col = Collection(args.db)
    try:
        cv = col.models.by_name("ChineseVocabulary")
        cv_id = cv["id"]
        IX = {f["name"]: i for i, f in enumerate(cv["flds"])}
        live_decks = {did for did, name in col.db.all("SELECT id, name FROM decks")
                      if "Hidden" not in name}

        # ── identify the targets: HSK 3.0 multi-char words with no ACTIVE ord=0 card ──
        rows = col.db.all("SELECT n.sfld, c.did, c.queue, c.ord, c.id, c.type, n.id, n.mid "
                          "FROM cards c JOIN notes n ON n.id=c.nid")
        active = {s for s, d, q, o, ci, ty, ni, m in rows
                  if o == 0 and d in live_decks and q != -1}
        missing = {w for w in level_of if len(w) > 1 and w not in active}
        targets = [(s, d, ci, ty, ni) for s, d, q, o, ci, ty, ni, m in rows
                   if s in missing and o == 0 and d in live_decks and q == -1 and m == cv_id]
        print(f"targets: {len(targets)} suspended ord=0 word cards "
              f"({sum(1 for t in targets if t[3] == 0)} new, {sum(1 for t in targets if t[3] != 0)} review)")

        # ── pass 1: glosses ─────────────────────────────────────────────────
        note_of = {s: ni for s, d, ci, ty, ni in targets}
        gloss_changes = []
        for word in gfix["replace"] + gfix["pinyin_only"]:
            nid = note_of.get(word)
            if nid is None:
                print(f"  WARN gloss target {word} not among suspended cards; skipped")
                continue
            ents = dict_entries(word)
            common = [e for e in ents if not re.match(r"^[A-Z]", e["pinyin"])]
            if not common:
                print(f"  WARN no common-word dict entry for {word}; skipped")
                continue
            note = col.get_note(nid)
            old_py, old_gl = note.fields[IX["Pinyin"]], note.fields[IX["Meaning"]]
            new_py = common[0]["pinyin"]
            new_gl = common[0]["defs"] if word in gfix["replace"] else old_gl
            gloss_changes.append((word, old_py, new_py, strip_html(old_gl)[:40], strip_html(new_gl)[:40]))
            if APPLY:
                note.fields[IX["Pinyin"]] = new_py
                note.fields[IX["Meaning"]] = new_gl
                col.update_note(note)
        print(f"\npass 1 GLOSS: {len(gloss_changes)} notes")
        for w, opy, npy, og, ng in gloss_changes:
            print(f"   {w:8} {opy:16}->{npy:16} | {og:40} -> {ng}")

        # ── pass 2: sentences ───────────────────────────────────────────────
        sent_done, sent_skip = 0, []
        for e in sentences:
            nid, word, simp, en = e["nid"], e["word"], e["sent"], e["en"]
            if word not in missing:
                sent_skip.append((word, "not a target")); continue
            if word not in simp:
                sent_skip.append((word, "word absent from sentence")); continue
            if not re.search(r"[。！？]$", simp):
                sent_skip.append((word, "no end punctuation")); continue
            trad = TO_TRAD(simp)
            wtrad = TO_TRAD(word)
            if wtrad not in trad:
                sent_skip.append((word, "word absent from traditional")); continue
            note = col.get_note(nid)
            if note.fields[IX["Simplified"]].strip() != word:
                sent_skip.append((word, f"nid {nid} is {note.fields[IX['Simplified']]}")); continue
            vals = {
                "SentenceSimplified": simp.replace(word, f"<b>{word}</b>", 1),
                "SentenceTraditional": trad.replace(wtrad, f"<b>{wtrad}</b>", 1),
                "SentenceSimplifiedCloze": simp.replace(word, "[ ]", 1),
                "SentenceTraditionalCloze": trad.replace(wtrad, "[ ]", 1),
                "SentencePinyin": sent_pinyin(simp),
                "SentenceMeaning": en,
            }
            if APPLY:
                for k, v in vals.items():
                    note.fields[IX[k]] = v
                col.update_note(note)
            sent_done += 1
            if sent_done <= 5:
                print(f"   {word:8} {simp}  /  {vals['SentencePinyin']}")
        print(f"\npass 2 SENTENCE: {sent_done} notes rewritten, {len(sent_skip)} skipped")
        for w, why in sent_skip:
            print(f"   SKIP {w}: {why}")

        # ── pass 3: unsuspend + splice into the new queue ───────────────────
        target_cids = [ci for s, d, ci, ty, ni in targets]
        if APPLY:
            col.sched.unsuspend_cards(target_cids)
        print(f"\npass 3 UNSUSPEND: {len(target_cids)} cards")

        LEVEL_ORDER = {str(i): i for i in range(1, 7)}
        LEVEL_ORDER["7-9"] = 7

        def key_for(word):
            return (LEVEL_ORDER.get(level_of.get(word, "7-9"), 9), -zipf_frequency(word, "zh"))

        by_deck = collections.defaultdict(list)
        for s, d, ci, ty, ni in targets:
            if ty == 0:
                by_deck[d].append((ci, s))

        for did, tgts in sorted(by_deck.items()):
            dname = col.decks.name(did)
            tgt_cids = {ci for ci, s in tgts}
            # current new ord=0 cards in this deck, in queue order (chars + vocab, incl. suspended)
            allrows = col.db.all(
                "SELECT c.id, c.due, n.sfld, n.mid FROM cards c JOIN notes n ON n.id=c.nid "
                "WHERE c.did=? AND c.type=0 AND c.ord=0 ORDER BY c.due, c.id", did)
            others = [(cid, sfld, mid) for cid, due, sfld, mid in allrows if cid not in tgt_cids]
            # keys of the non-target VOCAB cards define the queue's sort key at each index
            vocab_keys = [(i, key_for(strip_html(sfld)))
                          for i, (cid, sfld, mid) in enumerate(others) if mid == cv_id]

            def insert_index(k):
                for i, vk in vocab_keys:
                    if vk > k:
                        return i
                return len(others)

            spliced = list(others)
            for ci, s in sorted(tgts, key=lambda t: key_for(t[1]), reverse=True):
                spliced.insert(insert_index(key_for(s)), (ci, s, cv_id))

            order = [cid for cid, sfld, mid in spliced]
            assert len(order) == len(allrows) == len(set(order)), "reposition set mismatch"
            print(f"   {dname}: repositioning {len(order)} new cards "
                  f"({len(tgts)} spliced in, {len(others)} kept in place)")
            if APPLY:
                col.sched.reposition_new_cards(order, starting_from=1, step_size=1,
                                               randomize=False, shift_existing=False)

        # ── verification (must run BEFORE the bot restarts) ─────────────────
        print("\n── verify ──")
        still = col.db.scalar(
            "SELECT COUNT(*) FROM cards WHERE id IN (%s) AND queue=-1" %
            ",".join(str(c) for c in target_cids)) if target_cids else 0
        print(f"targets still suspended: {still} (want 0)" if APPLY else "(dry-run: no writes)")

        if APPLY:
            for did in sorted(by_deck):
                dname = col.decks.name(did)
                top = col.db.all(
                    "SELECT n.sfld, n.tags, c.queue FROM cards c JOIN notes n ON n.id=c.nid "
                    "WHERE c.did=? AND c.type=0 AND c.ord=0 AND c.queue!=-1 ORDER BY c.due LIMIT 10", did)
                print(f"   {dname} frontmost: " + " ".join(strip_html(s) for s, t, q in top))
            # spot-check a repaired note
            n = col.get_note(note_of["烈日"])
            print(f"   烈日 -> pinyin={n.fields[IX['Pinyin']]!r} meaning={strip_html(n.fields[IX['Meaning']])!r}")
            print(f"        sentence={strip_html(n.fields[IX['SentenceSimplified']])!r}")
            print(f"        pinyin  ={n.fields[IX['SentencePinyin']]!r}")
            print(f"        cloze   ={strip_html(n.fields[IX['SentenceSimplifiedCloze']])!r}")
            bad = col.db.scalar(
                "SELECT COUNT(*) FROM cards c WHERE c.id IN (%s) AND c.type=0 AND c.due<=0" %
                ",".join(str(c) for c in target_cids))
            print(f"   targets with non-positive new-queue position: {bad} (want 0)")
        print("\nDRY-RUN — nothing written. Re-run with --apply" if not APPLY else "\nAPPLIED.")
    finally:
        col.close()


if __name__ == "__main__":
    main()
