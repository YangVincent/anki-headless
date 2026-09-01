#!/usr/bin/env python3
"""Apply the subagent-generated sentence fields to the mined cards.

Reads freq_data/gen_mined/out_new_sent.json and out_tr_*.json (the convention from
freq_data/gen/: input JSON in, out_*.json back, applied by a script that validates).

IT ONLY EVER FILLS AN EMPTY FIELD. `Meaning` and `Pinyin` are never touched -- Vincent's
gloss rule is a short dictionary gloss, and 113 verbose rewrites from July were reverted
on 2026-08-01. improve_mined.py regenerates those; this does not.

FOUR CHECKS BEFORE ANY WRITE, each one a rejection rather than a warning:
  * the target word appears in the sentence (bolding is applied HERE, in code -- the
    agent is never trusted to emit markup);
  * for a card that already had a sentence, the returned sentence is byte-identical to
    the input -- the agents were told to copy it through, and this proves they did;
  * pinyin and translation are non-empty;
  * the nid's Simplified field still matches the word the agent was given.

  bash freq_data/anki_op.sh minedsent freq_data/apply_mined_sentences.py --apply
"""
import argparse
import glob
import json
import os
import re

from anki.collection import Collection

ROOT = "/home/vincent/anki-headless"
DIRS = [f"{ROOT}/freq_data/gen_mined", f"{ROOT}/freq_data/gen/freq_data/gen_mined"]


def clean(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def load(pattern):
    """First directory that has the file wins; the nested copy is a cwd-bug artefact."""
    seen, out = set(), []
    for d in DIRS:
        for fp in sorted(glob.glob(os.path.join(d, pattern))):
            base = os.path.basename(fp)
            if base in seen:
                continue
            seen.add(base)
            out.extend(json.load(open(fp, encoding="utf-8")))
    return out, sorted(seen)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    inputs = {}
    for d in DIRS:
        for fp in glob.glob(os.path.join(d, "*_input*.json")):
            for r in json.load(open(fp, encoding="utf-8")):
                inputs.setdefault(r["nid"], r)

    new_sent, f1 = load("out_new_sent.json")
    trs, f2 = load("out_tr_*.json")
    print(f"loaded {len(new_sent)} new sentences from {f1}")
    print(f"loaded {len(trs)} translations from {f2}")

    col = Collection(f"{ROOT}/collection.anki2")
    try:
        cv = col.models.by_name("ChineseVocabulary")
        F = {f["name"]: i for i, f in enumerate(cv["flds"])}
        good, bad = [], []
        for r in new_sent + trs:
            nid, w = r["nid"], r["word"]
            s = (r.get("sent_simp") or "").strip()
            py = (r.get("pinyin") or "").strip()
            en = (r.get("english") or "").strip()
            src = inputs.get(nid, {})
            if w not in s:
                bad.append((w, "sentence lacks the word", s)); continue
            if src.get("sent_simp") and s != src["sent_simp"]:
                bad.append((w, "rewrote the existing sentence", s)); continue
            if not py or not en:
                bad.append((w, "empty pinyin or translation", s)); continue
            note = col.get_note(nid)
            if note.fields[F["Simplified"]].strip() != w:
                bad.append((w, "nid no longer holds this word", s)); continue
            good.append((nid, w, s, py, en))

        print(f"\nvalidated: {len(good)} good, {len(bad)} rejected")
        for w, why, s in bad[:12]:
            print(f"   REJECT {w}: {why} -- {s[:46]}")
        if not args.apply:
            print("\nDRY-RUN (pass --apply)")
            return

        wrote = 0
        for nid, w, s, py, en in good:
            note = col.get_note(nid)
            touched = False
            if not clean(note.fields[F["SentenceSimplified"]]):
                note.fields[F["SentenceSimplified"]] = s.replace(w, f"<b>{w}</b>", 1)
                touched = True
            if not clean(note.fields[F["SentencePinyin"]]):
                note.fields[F["SentencePinyin"]] = py; touched = True
            if not clean(note.fields[F["SentenceMeaning"]]):
                note.fields[F["SentenceMeaning"]] = en; touched = True
            if touched:
                col.update_note(note); wrote += 1
        print(f"\nwrote {wrote} note(s)")

        miss = 0
        for nid, w, s, py, en in good:
            n = col.get_note(nid)
            if not (clean(n.fields[F["SentenceSimplified"]])
                    and clean(n.fields[F["SentencePinyin"]])
                    and clean(n.fields[F["SentenceMeaning"]])):
                miss += 1
        print(f"verify: applied notes still missing a sentence field = {miss}")
        assert miss == 0
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
