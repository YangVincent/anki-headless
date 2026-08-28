"""Repair the 度过/渡过 Homophone link, and give 渡过 the mirror usage rule.

Three defects, two of them mine:

  1. I wrote 度过's Homophone as "渡过 dùguò -- to cross (water); ...". The other 67
     entries in this notetype hold a bare word (公园->公元, 钥匙->要是). Format fixed.
  2. I filled one direction only. 67 of the 68 filled entries are reciprocal; the single
     one-way entry was the one I created. 渡过 now points back.
  3. A bare pointer tells 渡过 nothing about which word means what, and 渡过 had an empty
     Notes field. 度过 already carries the usage rule in Notes, so the mirror rule goes
     in the same field on 渡过 -- the pointer stays in Homophone, the rule stays in Notes.

Run through freq_data/anki_op.sh. Dry-run by default; pass --apply to write.
"""
import sys
from anki.collection import Collection

APPLY = "--apply" in sys.argv

EDITS = {
    1393817667154: {  # 度过
        "_expect": "度过",
        "Homophone": "渡过",
    },
    1708747494414: {  # 渡过
        "_expect": "渡过",
        "Homophone": "度过",
        "Notes": ("Object is water or a hardship: 渡过难关/危机, 渡过长江. "
                  "A stretch of time takes 度: 度过假期/童年. Both read dùguò."),
    },
}

col = Collection("/home/vincent/anki-headless/collection.anki2")
try:
    for nid, spec in EDITS.items():
        note = col.get_note(nid)
        idx = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
        word = note.fields[idx["Simplified"]]
        assert word == spec["_expect"], f"note {nid} is {word!r}"
        print(f"=== note {nid}  {word}")
        for field, new in spec.items():
            if field.startswith("_"):
                continue
            old = note.fields[idx[field]]
            print(f"    {field}:")
            print(f"        was: {old!r}")
            print(f"        now: {new!r}")
            note.fields[idx[field]] = new
        if APPLY:
            col.update_note(note)

    if APPLY:
        print("\n=== verify (re-read)")
        for nid, spec in EDITS.items():
            note = col.get_note(nid)
            idx = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            for field, new in spec.items():
                if field.startswith("_"):
                    continue
                got = note.fields[idx[field]]
                print(f"    {'OK  ' if got == new else 'FAIL'} {nid} {field}")
                assert got == new, (nid, field, got)
        # The reciprocity claim is the point of this script, so assert it directly.
        a = col.get_note(1393817667154)
        b = col.get_note(1708747494414)
        ia = {f["name"]: i for i, f in enumerate(a.note_type()["flds"])}
        assert a.fields[ia["Homophone"]] == b.fields[ia["Simplified"]]
        assert b.fields[ia["Homophone"]] == a.fields[ia["Simplified"]]
        print("    OK   link is reciprocal")
        print("APPLIED")
    else:
        print("DRY-RUN (pass --apply to write)")
finally:
    col.close()
