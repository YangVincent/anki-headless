#!/usr/bin/env python3
"""Apply generated example sentences to the weak/sparse archived cards.
Reads freq_data/gen/out_batch_*.json, derives bold + cloze, writes 6 sentence
sub-fields per note via the Anki API. Leaves SentenceAudio empty (TTS is a
separate follow-up). Validates that the target word appears in the sentence."""
import json, glob, re, sys
from anki.collection import Collection

COLLECTION = "/home/vincent/anki-headless/collection.anki2"

def clean(s): return re.sub(r"<[^>]+>", "", s or "").replace("\xa0"," ").strip()

def bold(sent, w):
    return sent.replace(w, f"<b>{w}</b>", 1) if w and w in sent else sent

def cloze(sent, w):
    return sent.replace(w, "[ ]", 1) if w and w in sent else sent

# ── load all generated batches ──
# --batch NAME restricts the run to one batch file. Without it this globs EVERY
# out_batch_*.json in freq_data/gen -- 11 files and 809 entries as of 2026-09-01 -- so
# applying a fresh batch of 78 would also rewrite the sentence fields of 544 notes from
# batches of unknown age. A tool that silently widens its own blast radius by a factor of
# seven is one nobody can use safely on a live collection.
_only = None
if "--batch" in sys.argv:
    _only = sys.argv[sys.argv.index("--batch") + 1]

gen = {}
bad_json = []
_files = ([f"freq_data/gen/out_batch_{_only}.json"] if _only
          else sorted(glob.glob("freq_data/gen/out_batch_*.json")))
for fp in _files:
    try:
        for e in json.load(open(fp)):
            gen[int(e["nid"])] = e
    except Exception as ex:
        bad_json.append((fp, str(ex)))
print(f"loaded {len(gen)} generated entries from {len(_files)} batch file(s)"
      + (f" (--batch {_only})" if _only else " (ALL batches)"))
if bad_json:
    print("  WARNING bad JSON files:", bad_json)

#: Set by shinian_deck.py on a note it creates with no example sentence. Must match.
NEEDS_SENTENCE = "needs::sentence"

APPLY = "--apply" in sys.argv
col = Collection(COLLECTION)
applied = skipped = cleared = 0
skips = []
try:
    nt_fields = {m["id"]: [f["name"] for f in m["flds"]] for m in col.models.all()}
    for nid, e in gen.items():
        try:
            note = col.get_note(nid)
        except Exception:
            skipped += 1; skips.append((nid, "note-missing")); continue
        names = [f["name"] for f in note.note_type()["flds"]]
        idx = {n: i for i, n in enumerate(names)}
        if "SentenceSimplified" not in idx:
            skipped += 1; skips.append((nid, "no-sentence-fields")); continue
        word = clean(note.fields[idx["Simplified"]]) or e.get("word","")
        trad_word = clean(note.fields[idx["Traditional"]]) or word
        s_simp, s_trad = e.get("sent_simp","").strip(), e.get("sent_trad","").strip()
        if not s_simp or word not in s_simp:
            skipped += 1; skips.append((nid, f"word-not-in-sent:{word}")); continue
        vals = {
            "SentenceSimplified": bold(s_simp, word),
            "SentenceTraditional": bold(s_trad, trad_word),
            "SentenceSimplifiedCloze": cloze(s_simp, word),
            "SentenceTraditionalCloze": cloze(s_trad, trad_word),
            "SentencePinyin": e.get("pinyin","").strip(),
            "SentenceMeaning": e.get("english","").strip(),
        }
        for k,v in vals.items():
            if k in idx: note.fields[idx[k]] = v
        # Clear the marker shinian_deck.py sets on a note it created without a sentence.
        # A marker nothing removes is worse than no marker: it survives the fix, so the
        # search that is supposed to list the outstanding work lists the finished work
        # too, and stops being read. This is the step that finishes that note.
        if NEEDS_SENTENCE in note.tags:
            note.remove_tag(NEEDS_SENTENCE)
            cleared += 1
        if APPLY:
            col.update_note(note)
        applied += 1
    print(f"{'APPLIED' if APPLY else 'DRY-RUN'}: {applied} notes updated, {skipped} skipped")
    print(f"  {NEEDS_SENTENCE} cleared on {cleared} of them; "
          f"{len(col.find_notes(f'tag:{NEEDS_SENTENCE}'))} notes still carry it")
    if skips[:15]: print("  sample skips:", skips[:15])
finally:
    col.close()
