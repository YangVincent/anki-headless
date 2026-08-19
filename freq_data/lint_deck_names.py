#!/usr/bin/env python3
"""Report scripts that name a deck which no longer exists.

A script naming a dead deck does not crash. `col.decks.id_for_name()` returns None and the
work silently does nothing — which is how the cloze gate and two background jobs ran for
months achieving nothing. This makes that measurable.

The live code path holds no deck-name literals at all (they come from decks.py). The
scripts below are hand-run one-shots kept as a record of past migrations; several predate
several renames. Nothing here is broken until someone re-runs one.

Exit code is the number of files naming a dead deck, so this can gate a check.
Usage: .venv/bin/python freq_data/lint_deck_names.py [--verbose]
"""
import glob, os, re, sys

sys.path.insert(0, "/home/vincent/anki-headless")
import decks

VERBOSE = "--verbose" in sys.argv
LIVE = set(decks.ALL_NAMES)
# Deck names this collection has used, current and retired. A literal matching one of
# these that is NOT in LIVE is a dead reference.
KNOWN = (r"HSK7-9|HSK|non-HSK|Mined|Reverse|Cloze|Archive|Hidden|Vocab Cloze|Vocab|"
         r"Knowledge|Calibration|hanly[\w-]*|Characters")
PAT = re.compile(rf'''["']((?:{KNOWN})(?:::[^"']*)?)["']''')

dead, clean = {}, []
for path in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "*.py"))):
    if os.path.basename(path) == os.path.basename(__file__):
        continue
    names = set()
    for line in open(path, encoding="utf-8", errors="replace"):
        if line.lstrip().startswith("#"):
            continue
        names |= {m.group(1) for m in PAT.finditer(line)}
    if not names:
        continue
    bad = sorted(n for n in names if n not in LIVE and n.split("::")[0] not in LIVE)
    (dead.setdefault(os.path.basename(path), bad) if bad
     else clean.append(os.path.basename(path)))

print(f"scripts naming a deck: {len(dead) + len(clean)}")
print(f"  all names resolve  : {len(clean)}")
print(f"  names a DEAD deck  : {len(dead)}")
if dead:
    from collections import Counter
    c = Counter(n for v in dead.values() for n in v)
    print("\ndead names still written:")
    for n, k in c.most_common():
        print(f"   {n!r:28s} in {k} script(s)")
    if VERBOSE:
        print("\nby file:")
        for f, names in sorted(dead.items()):
            print(f"   {f:34s} {', '.join(names)}")
    else:
        print("\n(--verbose lists the files)")
print(f"\nlive decks: {', '.join(sorted(LIVE))}")
sys.exit(len(dead))
