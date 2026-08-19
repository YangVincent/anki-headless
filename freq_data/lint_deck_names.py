#!/usr/bin/env python3
"""Report live code that names a deck which no longer exists.

A script naming a dead deck does not crash. `col.decks.id_for_name()` returns None and
the work silently does nothing — which is how the cloze gate and two background jobs ran
for months achieving nothing. This makes that measurable.

Three things the first version got wrong, each of which made its green result worthless:

  * It globbed `freq_data/*.py` only, so `bot.py` held a dead
    `deck:Hidden::hanly-grammar` search for a whole session while this reported 0. It now
    scans the whole live tree.
  * Its pattern required the deck name to start immediately after the quote, so it could
    not see `deck:Vocab` inside an Anki search string — the form of every historical
    instance of this bug. There are two patterns now.
  * It scanned raw lines, so it counted comments and docstrings, and flagged the very
    notes written to record each fix. It now reads real string literals via the AST,
    because only those can name a deck at run time.

`freq_data/applied/` is skipped on purpose: those scripts are retired BECAUSE they name
dead decks. `decks.py` is skipped because it IS the definition.

Exit code is the number of files naming a dead deck, so this can gate a check.
Usage: .venv/bin/python freq_data/lint_deck_names.py [--verbose]
"""
import ast
import glob
import os
import re
import sys
from collections import Counter

sys.path.insert(0, "/home/vincent/anki-headless")
import decks  # noqa: E402

VERBOSE = "--verbose" in sys.argv
LIVE = set(decks.ALL_NAMES)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_FILES = {"lint_deck_names.py", "decks.py"}
SKIP_DIRS = {"applied"}

# Deck names this collection has used, current and retired. `hanly` alone is NOT here: it
# is a live tag on 4,637 notes as well as a dead deck, and a linter that cannot tell them
# apart flags `tag:hanly` forever.
KNOWN = (r"HSK7-9|HSK|non-HSK|Mined|Reverse|Cloze|Archive|Hidden|Vocab Cloze|Vocab|"
         r"Knowledge|Calibration|hanly-(?:reverse|grammar|proper-nouns)[\w-]*|Characters")
QUOTED = re.compile(rf'^((?:{KNOWN})(?:::[^\s"\']*)?)$')
IN_SEARCH = re.compile(rf'deck:"?((?:{KNOWN})(?:::[^"\'\s]*)?)')


def deck_names_in(path):
    """Deck names appearing in real string literals. None if the file will not parse."""
    try:
        tree = ast.parse(open(path, encoding="utf-8", errors="replace").read(), filename=path)
    except SyntaxError:
        return None
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
           and body and isinstance(body[0], ast.Expr) \
           and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            docstrings.add(id(body[0].value))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
           and id(node) not in docstrings:
            m = QUOTED.match(node.value.strip())
            if m:
                found.add(m.group(1))
            found |= {s.group(1) for s in IN_SEARCH.finditer(node.value)}
    return found


def targets():
    for sub in ("", "freq_data", "quality", "tools"):
        for path in glob.glob(os.path.join(ROOT, sub, "*.py")):
            if os.path.basename(path) in SKIP_FILES:
                continue
            if os.path.basename(os.path.dirname(path)) in SKIP_DIRS:
                continue
            yield path


def main():
    dead, clean, unparsed = {}, [], []
    for path in sorted(set(targets())):
        names = deck_names_in(path)
        rel = os.path.relpath(path, ROOT)
        if names is None:
            unparsed.append(rel)
            continue
        if not names:
            continue
        bad = sorted(n for n in names if n not in LIVE and n.split("::")[0] not in LIVE)
        (dead.setdefault(rel, bad) if bad else clean.append(rel))

    print(f"live files naming a deck: {len(dead) + len(clean)}")
    print(f"  all names resolve     : {len(clean)}")
    print(f"  names a DEAD deck     : {len(dead)}")
    if unparsed:
        print(f"  could not parse       : {len(unparsed)} ({', '.join(unparsed)})")
    if dead:
        print("\ndead names still written in code:")
        for n, k in Counter(n for v in dead.values() for n in v).most_common():
            print(f"   {n!r:44s} in {k} file(s)")
        print("\nby file:")
        for f, names in sorted(dead.items()):
            print(f"   {f:38s} {', '.join(names)}")
    print(f"\nlive decks: {', '.join(sorted(LIVE))}")
    return len(dead)


if __name__ == "__main__":
    sys.exit(main())
