"""Mechanical field checks over the ChineseVocabulary notes.

WHY THIS EXISTS. The 度过/渡过 session found four field defects by hand, one at a time,
and each hand-fix needed its own stopped-bot window. Two of the four were introduced by
the hand-fix before it. A rule that lives in a person's head gets applied to the one card
in front of them; a rule that lives here gets applied to all 49,930.

READ-ONLY AND LOCK-FREE. It opens collection.anki2 with `mode=ro` and never imports
`anki`, so it runs while the bot is live. Only --fix needs freq_data/anki_op.sh.

NO SQL NAME LOOKUP. notetypes.name and decks.name carry Anki's `unicase` collation, so
`where name = ?` raises on a raw connection. Every name match happens in Python.

ONLY RENDERED FIELDS. The rules run against the fields the templates actually show. In
this notetype SentenceTraditional, SentenceTraditionalCloze and Frequency are rendered by
no template, and checking them produced 3723 violations the user can never see. The set
is derived from the templates at run time, so a template edit re-scopes the linter.

WHAT BELONGS HERE. Only deterministic rules -- a violation must be decidable from the
fields alone, with one correct repair. Style judgments are NOT rules. This session called
three of them defects (an empty Traditional, pinyin spacing, gloss wording) and
measurement showed all three were the collection's own norm.

CALIBRATION. Every rule prints its violation rate. A rule above the noise line is
describing the norm; fix the rule, not the cards.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys

COL = "/home/vincent/anki-headless/collection.anki2"
NOTETYPE = "ChineseVocabulary"
BLANK = "[ ]"
HAN = re.compile(r"[一-鿿㐀-䶿]")
B_TAG = re.compile(r"</?b>", re.I)
PAREN = re.compile(r"[（(][^）)]*[）)]")          # 可怕（的） -> 可怕
HOMO_SEP = re.compile(r"[，,、/;；\s]+")          # 形势，刑事 is one valid entry
NOISE_RATE = 5.0                                   # percent; above this, suspect the rule


def strip_b(s):
    return B_TAG.sub("", s)


def bare(word):
    """The word as it appears inside a sentence, without a field-only parenthetical."""
    return PAREN.sub("", word).strip()


def load(con):
    cur = con.cursor()
    mid = next((i for i, n in cur.execute("select id, name from notetypes")
                if n == NOTETYPE), None)
    if mid is None:
        sys.exit(f"notetype {NOTETYPE!r} not found")
    names = [r[0] for r in cur.execute(
        "select name from fields where ntid = ? order by ord", (mid,))]

    rendered = set()
    for (cfg,) in cur.execute("select config from templates where ntid = ?", (mid,)):
        text = cfg.decode("utf-8", "replace")
        for f in names:
            if re.search(r"\{\{[^}]*\b" + re.escape(f) + r"\b[^}]*\}\}", text):
                rendered.add(f)

    decks = {i: n.replace("\x1f", "::") for i, n in cur.execute("select id, name from decks")}
    live = {nid for (nid,) in cur.execute(
        "select distinct nid from cards where ord = 0 and queue >= 0")}
    deck_of = {nid: decks.get(did, "?")
               for nid, did in cur.execute("select nid, did from cards where ord = 0")}

    notes = {}
    for nid, flds in cur.execute("select id, flds from notes where mid = ?", (mid,)):
        v = flds.split("\x1f")
        notes[nid] = {n: (v[i] if i < len(v) else "") for i, n in enumerate(names)}
    return notes, rendered, live, deck_of



# --- word surfaces and word boundaries --------------------------------------
# Both of these exist because the naive versions produced false positives that this
# session then reported to the user as card defects. Measure before you believe a rule.

HTML_TAG = re.compile(r"<[^>]+>")
PATTERN_GAP = re.compile(r"。。。|\.\.\.|…")
NOTATION = re.compile(r"[＃#*＊]")


def strip_html(s):
    return HTML_TAG.sub("", s)


def surface_forms(word):
    """The shapes a Simplified field can take inside a sentence, and how to test them.

    Returns (forms, mode). mode "all" means every form must appear -- that is a grammar
    pattern like 一边。。。一边, where the field is not a word at all. mode "any" means one
    form is enough, because the field carries notation the sentence does not: 多（一）点
    appears as 多一点, and 有用＃ appears as 有用.
    """
    w = strip_html(word).strip()
    if not w:
        return set(), "any"
    if PATTERN_GAP.search(w):
        segs = {x.strip() for x in PATTERN_GAP.split(w) if x.strip()}
        return segs, "all"
    forms = {w,
             PAREN.sub("", w).strip(),               # 多（一）点 -> 多点
             re.sub(r"[（(）)]", "", w).strip(),      # 多（一）点 -> 多一点
             NOTATION.sub("", w).strip()}            # 有用＃      -> 有用
    return {f for f in forms if f}, "any"


_JIEBA = None


def _jieba():
    global _JIEBA
    if _JIEBA is None:
        import jieba
        jieba.initialize()
        _JIEBA = jieba
    return _JIEBA


def standalone_spans(text, word):
    """Character spans where `word` sits on jieba token boundaries at both ends.

    Token EQUALITY is not the test. jieba splits 有的 into 有/的, so an equality test
    finds no occurrence in 有的人喜欢咖啡 and the real leak goes unreported. Alignment is
    the test, and it also excludes the opposite error: 卖国 inside 出卖|国家机密 starts
    mid-token, so it is a cross-boundary fragment and not an occurrence of the word.
    """
    plain = strip_html(text)
    toks = list(_jieba().tokenize(plain))
    starts = {a for _t, a, _b in toks}
    ends = {b for _t, _a, b in toks}
    out, i = [], plain.find(word)
    while i != -1:
        if i in starts and i + len(word) in ends:
            out.append((i, i + len(word)))
        i = plain.find(word, i + 1)
    return out


def present_form(text, forms):
    """The longest surface form that actually appears, or None."""
    plain = strip_html(text)
    hits = [f for f in forms if f in plain]
    return max(hits, key=len) if hits else None


# --- rules -------------------------------------------------------------------
# Each rule yields (nid, detail, repair). A repair is {field: value}, or None when the
# right answer needs a person. `ctx` carries `rendered` and the word->note index.

def rule_sentence_missing_word(nid, f, ctx):
    if "SentenceSimplified" not in ctx["rendered"]:
        return
    s = f["SentenceSimplified"]
    forms, mode = surface_forms(f["Simplified"])
    if not (s.strip() and forms):
        return
    plain = strip_html(strip_b(s))
    if mode == "all":
        missing = [x for x in sorted(forms) if x not in plain]
        if missing:
            yield nid, f"pattern segment(s) absent: {missing}", None
    elif not any(x in plain for x in forms):
        yield nid, f"sentence lacks any of {sorted(forms)}", None


def rule_sentence_not_bold(nid, f, ctx):
    """Flag only when NO surface form is bolded.

    An earlier version bolded the LONGEST form that appeared, and wanted to rewrite
    <b>可怕</b>的 as <b>可怕的</b> across ten cards. The headword is the base form, and the
    existing markup was right every time. Any bolded form satisfies the rule.
    """
    if "SentenceSimplified" not in ctx["rendered"]:
        return
    s = f["SentenceSimplified"]
    forms, mode = surface_forms(f["Simplified"])
    if not s.strip() or mode == "all" or not forms:
        return
    if any(f"<b>{x}</b>" in s for x in forms):
        return
    w = present_form(strip_b(s), forms)
    if w:
        yield nid, f"{w!r} is not bold", {
            "SentenceSimplified": strip_b(s).replace(w, f"<b>{w}</b>", 1)}


def _cloze_pairs(ctx):
    for src, cz, wf in (("SentenceSimplified", "SentenceSimplifiedCloze", "Simplified"),
                        ("SentenceTraditional", "SentenceTraditionalCloze", "Traditional")):
        if cz in ctx["rendered"]:
            yield src, cz, wf


def rule_cloze_leaks_answer(nid, f, ctx):
    """The blank must hide the word. A cloze that still shows it is not a test.

    The repair is derived from SentenceSimplified, not from the stored cloze: where the
    stored blank landed inside a longer word the stored text is already damaged. 图书 read
    "[ ]馆里...的图书" -- the blank had eaten 图书馆 and left the real 图书 on screen.
    Blanking every standalone span of the sentence gives "图书馆里...的[ ]" instead.
    """
    for src, cz, wf in _cloze_pairs(ctx):
        text = f[cz]
        forms, mode = surface_forms(f[wf])
        if not (text.strip() and forms) or mode == "all":
            continue
        w = present_form(text, forms)
        if w is None:
            continue
        if not standalone_spans(text, w):
            continue                     # a cross-boundary fragment, not the word
        repair = None
        sent = strip_b(f[src])
        spans = standalone_spans(sent, w)
        if spans:
            out, prev = [], 0
            for a, b in spans:
                out.append(strip_html(sent)[prev:a]); out.append(BLANK); prev = b
            out.append(strip_html(sent)[prev:])
            cand = "".join(out)
            if not standalone_spans(cand, w):
                repair = {cz: cand}
        yield nid, f"{cz} still shows {w!r}", repair


def rule_cloze_no_blank(nid, f, ctx):
    for _src, cz, _wf in _cloze_pairs(ctx):
        if f[cz].strip() and BLANK not in f[cz]:
            yield nid, f"{cz} has no {BLANK}", None


# DELETED: rule_cloze_mismatch. It rebuilt the cloze from SentenceSimplified and
# flagged any difference. Inspection of all 19 hits showed the STORED value was right
# every time and the derivation was wrong:
#   一边  他喜欢[ ]看书，[ ]听音卥  -- 一边...一边 needs both halves blanked; the
#         derivation blanked the first only and left the answer on screen.
#   点头  她听了我的建议，[ ]了[ ]。 -- 点了点头 is a split verb, blanked in two places.
#   认识  the derivation re-inserted the <div> wrapper it had not stripped.
# A rule that loses to the data it checks does not belong here.

def _homo_targets(f):
    h = f["Homophone"].strip()
    return [t for t in HOMO_SEP.split(h) if t] if h else []


def rule_homophone_format(nid, f, ctx):
    """Entries hold bare words, separated by a comma. 67 of 68 look exactly like that."""
    if "Homophone" not in ctx["rendered"]:
        return
    for t in _homo_targets(f):
        if HAN.sub("", t):
            yield nid, f"Homophone entry is not a bare word: {t!r}", None


def rule_homophone_dangling(nid, f, ctx):
    if "Homophone" not in ctx["rendered"]:
        return
    for t in _homo_targets(f):
        if HAN.sub("", t):
            continue  # rule_homophone_format owns this one
        if t not in ctx["by_word"]:
            yield nid, f"Homophone points at {t!r}, which has no note", None


def rule_homophone_not_reciprocal(nid, f, ctx):
    """If A names B, B must name A. Otherwise only one of the pair warns the user."""
    if "Homophone" not in ctx["rendered"]:
        return
    me = f["Simplified"]
    for t in _homo_targets(f):
        other = ctx["by_word"].get(t)
        if other is None or HAN.sub("", t):
            continue
        if me not in _homo_targets(other):
            back = ", ".join(_homo_targets(other)) or "(empty)"
            yield nid, f"{t!r} does not point back (it has {back})", None


def _rename_safe(nid, clean, ctx):
    """A rename that lands on an existing headword is not a repair, it is a duplicate.

    有用＃ looked like a stray mark. The ＃ was in fact put there to get past Anki's
    duplicate warning: 有用 already exists, tagged HSK1 and mature at a 376-day interval.
    Stripping the mark would have created a second 有用. Always check the target first.
    """
    other = ctx["by_word"].get(clean)
    return other is None or ctx["nid_of"].get(clean) == nid


def rule_field_has_html(nid, f, ctx):
    """The card front renders Simplified raw, so a stray tag reaches the screen."""
    if not HTML_TAG.search(f["Simplified"]):
        return
    clean = strip_html(f["Simplified"]).strip()
    yield nid, "Simplified holds an HTML tag", (
        {"Simplified": clean} if _rename_safe(nid, clean, ctx) else None)


def rule_field_has_notation(nid, f, ctx):
    """A stray ＃ in the headword. Measured: exactly 1 note of 49,930 carries one, so it
    is a typo. The 67 notes carrying （的）/（了）/（来） are deliberate notation -- the
    PAREN branch of surface_forms() handles those, and they are not flagged.
    """
    w = f["Simplified"]
    if not NOTATION.search(w):
        return
    clean = NOTATION.sub("", w).strip()
    if _rename_safe(nid, clean, ctx):
        yield nid, f"Simplified holds a stray mark: {w!r}", {"Simplified": clean}
    else:
        yield nid, f"{w!r} is {clean!r} plus a mark that dodges the duplicate check", None


def rule_duplicate_headword(nid, f, ctx):
    """Two LIVE notes for one word. The philosophy is one comprehensive card per word.

    Liveness is the whole rule. A plain twin count reported 11 pairs, and 10 of them were
    the collection working as intended: the older note is HSK-tagged and studied, and the
    2025-12-25 `personal` import beside it already sits suspended in Archive. Parking a
    duplicate that way IS the fix, so counting it as a defect just re-reports the fix.
    Only a word with two unsuspended cards makes the user study the same thing twice.

    Reported, never auto-fixed: which note survives depends on the study history, and the
    loser has to be suspended or deleted by a person.
    """
    key = NOTATION.sub("", strip_html(f["Simplified"])).strip()
    twins = [t for t in ctx["nids_of"].get(key, ()) if t in ctx["live"]]
    if len(twins) > 1 and nid == min(twins):
        yield nid, f"{key!r} has {len(twins)} live notes: {sorted(twins)}", None


RULES = [
    ("duplicate-headword", rule_duplicate_headword),
    ("field-has-html", rule_field_has_html),
    ("field-has-notation", rule_field_has_notation),
    ("sentence-missing-word", rule_sentence_missing_word),
    ("sentence-not-bold", rule_sentence_not_bold),
    ("cloze-leaks-answer", rule_cloze_leaks_answer),
    ("cloze-no-blank", rule_cloze_no_blank),
    ("homophone-format", rule_homophone_format),
    ("homophone-dangling", rule_homophone_dangling),
    ("homophone-not-reciprocal", rule_homophone_not_reciprocal),
]


def collect(scope, notes, ctx, only=None):
    out = {}
    for name, fn in RULES:
        if only and name not in only:
            continue
        hits = []
        for nid, f in scope.items():
            hits.extend(fn(nid, f, ctx))
        out[name] = hits
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # DEFAULT IS THE STUDIED SET, and --all is the opt-out, because the two scopes
    # disagree about what a defect is. Over the whole notetype sentence-not-bold fires on
    # 21.87% of notes: the ~31k suspended archive notes were never bolded, so unbolded is
    # their norm. A --fix over that scope would rewrite 10,921 notes nobody reads.
    ap.add_argument("--all", dest="live_only", action="store_false", default=True,
                    help="include suspended notes (the archive pool; expect noise)")
    ap.add_argument("--live-only", dest="live_only", action="store_true",
                    help="only notes whose ord0 card is unsuspended (the default)")
    ap.add_argument("--deck", action="append", help="restrict to a deck (repeatable)")
    ap.add_argument("--rule", action="append", help="run only these rules")
    ap.add_argument("--show", type=int, default=5, help="examples per rule")
    ap.add_argument("--fix", action="store_true",
                    help="write the repairs (run through freq_data/anki_op.sh)")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{COL}?mode=ro", uri=True)
    notes, rendered, live, deck_of = load(con)
    con.close()

    scope = {nid: f for nid, f in notes.items()
             if (not args.live_only or nid in live)
             and (not args.deck or deck_of.get(nid) in args.deck)}
    # Reciprocity resolves against every note. A partner outside the scope is still a note.
    by_word = {}
    for f in notes.values():
        by_word.setdefault(f["Simplified"], f)
    nid_of, nids_of = {}, {}
    for nid, f in notes.items():
        key = NOTATION.sub("", strip_html(f["Simplified"])).strip()
        nid_of.setdefault(key, nid)
        nids_of.setdefault(key, []).append(nid)
    ctx = {"rendered": rendered, "by_word": by_word,
           "nid_of": nid_of, "nids_of": nids_of, "live": live}

    print(f"{NOTETYPE}: {len(notes)} notes, {len(scope)} in scope"
          f"{' (unsuspended ord0)' if args.live_only else ' (ALL, archive included)'}")
    if args.deck:
        print(f"decks: {', '.join(args.deck)}")
    unrendered = sorted(set(next(iter(notes.values())).keys()) - rendered)
    print(f"skipped, no template renders them: {', '.join(unrendered) or '(none)'}\n")

    results = collect(scope, notes, ctx, args.rule)
    total = fixable = 0
    for name, hits in results.items():
        rate = 100.0 * len({h[0] for h in hits}) / max(len(scope), 1)
        warn = "  <-- above the noise line; suspect the RULE" if rate > NOISE_RATE else ""
        n_fix = sum(1 for h in hits if h[2])
        print(f"{name:26s} {len(hits):5d} violations ({rate:5.2f}%)"
              f"  {n_fix} auto-fixable{warn}")
        for nid, detail, rep in hits[:args.show]:
            mark = "fix" if rep else "   "
            print(f"      {mark} {scope[nid]['Simplified']:8s} [{deck_of.get(nid,'?')}] {detail}")
        if len(hits) > args.show:
            print(f"          ... and {len(hits)-args.show} more")
        total += len(hits)
        fixable += n_fix
    print(f"\ntotal: {total} violations, {fixable} auto-fixable")

    if args.fix:
        if not fixable:
            print("nothing to fix")
            return 0
        from anki.collection import Collection  # imported ONLY under --fix
        col = Collection(COL)
        try:
            written = 0
            for name, hits in results.items():
                for nid, detail, rep in hits:
                    if not rep:
                        continue
                    note = col.get_note(nid)
                    idx = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
                    for field, value in rep.items():
                        print(f"  [{name}] {note.fields[idx['Simplified']]} {field}")
                        print(f"      was: {note.fields[idx[field]]!r}")
                        print(f"      now: {value!r}")
                        note.fields[idx[field]] = value
                    col.update_note(note)
                    written += 1
            print(f"\nwrote {written} note(s); re-running the rules to verify")
            con = sqlite3.connect(f"file:{COL}?mode=ro", uri=True)
            notes2, rendered2, _l, _d = load(con)
            con.close()
            scope2 = {nid: notes2[nid] for nid in scope if nid in notes2}
            ctx2 = dict(ctx, rendered=rendered2)
            left = sum(1 for hs in collect(scope2, notes2, ctx2, args.rule).values()
                       for h in hs if h[2])
            print(f"auto-fixable remaining: {left}")
            assert left == 0, "a repair did not take"
            print("APPLIED")
        finally:
            col.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
