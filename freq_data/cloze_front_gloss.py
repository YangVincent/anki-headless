#!/usr/bin/env python3
"""Update the Cloze-Recall front template: add the target word's English gloss
({{Meaning}}) to the prompt so the blank is disambiguated (事件 vs 事情) without
showing the full sentence translation. Template-text edit only (no schema change).
Dry-run unless --apply. Run via anki_op.sh."""
import sys
from anki.collection import Collection
APPLY = "--apply" in sys.argv
ROOT = "/home/vincent/anki-headless"

NEW_QFMT = """{{#SentenceSimplifiedCloze}}
<div class=title>Fill the blank — the word meaning &ldquo;{{Meaning}}&rdquo;. Say it.</div>
<div class=chinese>{{SentenceSimplifiedCloze}}</div>
{{/SentenceSimplifiedCloze}}"""

col = Collection(f"{ROOT}/collection.anki2")
try:
    cv = col.models.by_name("ChineseVocabulary")
    t = next((t for t in cv['tmpls'] if t['name'] == "Cloze-Recall"), None)
    if t is None:
        print("no Cloze-Recall template found"); sys.exit(1)
    print("--- current front ---"); print(t['qfmt'])
    print("--- new front ---"); print(NEW_QFMT)
    if APPLY:
        t['qfmt'] = NEW_QFMT
        col.models.update_dict(cv)
        print("APPLIED: Cloze-Recall front updated.")
    else:
        print("DRY-RUN (use --apply)")
finally:
    col.close()
