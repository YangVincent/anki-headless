#!/usr/bin/env python3
"""Add a visible "⛏ mined" badge to the ChineseVocabulary Hanzi-English card (ord 0)
that appears during review when the note has the 'mined' tag (showing the source, e.g.
水浒传, when tagged 'shuihu'). Template-text edit only (no schema change). Idempotent.
Dry-run unless --apply. Run via anki_op.sh."""
import sys
from anki.collection import Collection
APPLY = "--apply" in sys.argv
ROOT = "/home/vincent/anki-headless"
MARK = "minedbadge"

BADGE = """
<div id="minedbadge"></div>
<script>(function(){var t=" {{Tags}} ";if(t.indexOf(' mined ')>=0){var s=(t.indexOf(' shuihu ')>=0)?'⛏ 水浒传 mined':'⛏ mined';var e=document.getElementById('minedbadge');if(e)e.innerHTML='<span class="minedtag">'+s+'</span>';}})();</script>"""

CSS = """
.minedtag{display:inline-block;font-family:"DM Sans",-apple-system,sans-serif;font-size:12px;font-weight:500;color:#fff;background:#4a90d9;border-radius:11px;padding:2px 11px;margin-top:10px;letter-spacing:.3px}
.card.night_mode .minedtag{background:#3a6ea5;color:#eee}"""

col = Collection(f"{ROOT}/collection.anki2")
try:
    cv = col.models.by_name("ChineseVocabulary")
    t0 = next(t for t in cv['tmpls'] if t['ord'] == 0)
    changed = False
    if MARK not in t0['qfmt']:
        t0['qfmt'] = t0['qfmt'].rstrip() + "\n" + BADGE
        changed = True
        print("front template: badge ADDED")
    else:
        print("front template: badge already present")
    if ".minedtag" not in cv['css']:
        cv['css'] = cv['css'].rstrip() + "\n" + CSS
        changed = True
        print("css: .minedtag ADDED")
    else:
        print("css: .minedtag already present")
    print("--- new front (tail) ---")
    print(t0['qfmt'][-260:])
    if APPLY and changed:
        col.models.update_dict(cv)
        print("APPLIED.")
    elif not APPLY:
        print("DRY-RUN (use --apply)")
    else:
        print("nothing to change.")
finally:
    col.close()
