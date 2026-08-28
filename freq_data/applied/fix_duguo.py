"""Separate 度过 from 渡过.

The 度过 card carried the gloss for 渡过 ("pass (through); get through"), which is why
its own example sentence ("I spent the holidays abroad") did not confirm the answer.
The 渡过 card carried the overlapping "to pass through", and its example sentence put
渡过 with 时光 -- a stretch of time, which the standard rule assigns to 度.

Four edits, approved 2026-08-28:
  1. 度过 Meaning   -> the time sense only.
  2. 度过 Homophone -> point at 渡过 (the notetype has the field; 67 notes use it).
  3. 渡过 Meaning   -> water + crisis, no overlap with 度过.
  4. 渡过 sentence  -> 难关, so the pair stops teaching each other's word.

Run through freq_data/anki_op.sh. Dry-run by default; pass --apply to write.
"""
import sys
from anki.collection import Collection

APPLY = "--apply" in sys.argv

DUGUO_TIME = 1393817667154   # 度过, ChineseVocabulary, deck HSK
DUGUO_WATER = 1708747494414  # 渡过, ChineseVocabulary, deck HSK7-9

EDITS = {
    DUGUO_TIME: {
        "_expect": "度过",
        "Meaning": "to spend (time); to pass (a period)",
        "Homophone": "渡过 dùguò — to cross (water); to get through (a crisis)",
    },
    DUGUO_WATER: {
        "_expect": "渡过",
        "Meaning": "to cross (water); to get through (a crisis)",
        "SentenceSimplified": "靠着大家的帮助，公司<b>渡过</b>了这次难关。",
        "SentenceTraditional": "靠著大家的幫助，公司<b>渡過</b>了這次難關。",
        "SentenceSimplifiedCloze": "靠着大家的帮助，公司[ ]了这次难关。",
        "SentenceTraditionalCloze": "靠著大家的幫助，公司[ ]了這次難關。",
        "SentencePinyin": "Kàozhe dàjiā de bāngzhù, gōngsī dùguò le zhè cì nánguān.",
        "SentenceMeaning": "With everyone's help, the company got through this crisis.",
    },
}

col = Collection("/home/vincent/anki-headless/collection.anki2")
try:
    changed = 0
    for nid, spec in EDITS.items():
        note = col.get_note(nid)
        names = [f["name"] for f in note.note_type()["flds"]]
        idx = {n: i for i, n in enumerate(names)}
        word = note.fields[idx["Simplified"]]
        assert word == spec["_expect"], f"note {nid} is {word!r}, expected {spec['_expect']!r}"
        print(f"=== note {nid}  {word}")
        # A stale SentenceAudio would still play the old sentence. Refuse rather than lie.
        if "SentenceSimplified" in spec and note.fields[idx["SentenceAudio"]].strip():
            sys.exit(f"ABORT: note {nid} has SentenceAudio for the OLD sentence; handle it first")
        for field, new in spec.items():
            if field.startswith("_"):
                continue
            old = note.fields[idx[field]]
            if old == new:
                print(f"    {field}: already correct")
                continue
            print(f"    {field}:")
            print(f"        was: {old!r}")
            print(f"        now: {new!r}")
            note.fields[idx[field]] = new
            changed += 1
        if APPLY:
            col.update_note(note)
    print(f"\n{changed} field(s) {'written' if APPLY else 'to write'}")

    if APPLY:
        print("\n=== verify (re-read from the collection)")
        for nid, spec in EDITS.items():
            note = col.get_note(nid)
            idx = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            for field, new in spec.items():
                if field.startswith("_"):
                    continue
                got = note.fields[idx[field]]
                print(f"    {'OK  ' if got == new else 'FAIL'} {nid} {field}")
                assert got == new, (nid, field, got)
        print("APPLIED")
    else:
        print("DRY-RUN (pass --apply to write)")
finally:
    col.close()
