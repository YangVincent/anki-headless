#!/usr/bin/env python3
"""Drop HSK::HSKn tags that contradict the official HSK 3.0 band for the note's word.

hsk_retag_official.py guarantees the CORRECT tag is present, but it does not remove a
stale extra one, so a handful of notes carry two levels at once:

    拿    HSK::HSK1 + HSK::HSK7-9     official: level 1 only
    蓝    HSK::HSK2 + HSK::HSK7-9     official: level 2 only
    凉快  HSK::HSK2 + HSK::HSK4       official: level 2 only

That matters because resort_main_queue.level_of() reads the tag, so a note claiming two
levels sorts by whichever it sees first. 96 HSK 3.0 words genuinely sit in two bands, and
those are left alone — only tags OUTSIDE a word's official band(s) are removed.

Scope: notes with at least one card outside the Archive deck. Every Archive card is
suspended and it exists as a frozen backup pool, so its stale tags are inert for STUDY
and rewriting them would only churn the backup.

--include-archive widens that scope, because "inert" stopped being true. Archive travels
now: `anki-cli export --search "tag:HSK"` carries Archive notes into the .apkg, so a
shared HSK 3.0 deck ships every stale Archive tag to the recipient. 59 of the 203 wrong
tags sit on notes tagged HSK::HSK3, which is a deck that has already gone out. A tag
nobody studies is still a tag somebody reads.

Two further reconciliations, both opt-in because they express a POLICY rather than a
contradiction, and both restricted to notetypes whose field 0 is a word:

  --tag-untagged      A listed word carrying no HSK tag at all gets its band. 395 notes,
                      378 of them single characters in Archive.
  --prune-non-official  A word the standard does not contain carries no HSK tag, neither
                      HSK nor HSK::HSKn. 黄河, 打篮球, 秋 and 哈 are real words; they are
                      not HSK 3.0 headwords, and a level on them is invented.

NOT reconciled, deliberately: the 5,625 ChineseSentences notes. Field 0 there is a
sentence, so a word->level list cannot rule on it, and the tags follow no derivable rule
-- measured against the official list they match the sentence's hardest word 25% of the
time, its easiest 12%, any word in it 44%. Only 699 of them even match a vocabulary
note's example sentence, and 575 of those disagree with the tag. Rewriting them would
replace a tag of unknown origin with a tag of invented origin, which is worse: the second
one looks authoritative. They are skipped by NOTETYPE, not by a heuristic on the text,
because a heuristic that guesses "is this a word" would eventually guess wrong on 认真地听
and silently strip a note the standard says nothing about.

Usage:
    freq_data/hsk_fix_duplicate_level_tags.py                 # dry run, live notes only
    freq_data/hsk_fix_duplicate_level_tags.py --include-archive
    bash freq_data/anki_op.sh hsk-dupe-tags \\
         freq_data/hsk_fix_duplicate_level_tags.py --apply [--include-archive] \\
         [--tag-untagged] [--prune-non-official]
"""
import argparse
import json
import re

from anki.collection import Collection

ROOT = "/home/vincent/anki-headless"
OFFICIAL = f"{ROOT}/freq_data/hsk30_official.json"
TAG = re.compile(r"^HSK::HSK([1-6]|7-9)$")
HANZI = re.compile(r"^[一-鿿〇]+$")


def strip_html(s):
    return re.sub(r"<[^>]+>|\[sound:[^\]]*\]", "", s or "").replace("&nbsp;", " ").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--include-archive", action="store_true",
                    help="Also fix Archive-only notes. Use before exporting a deck to "
                         "somebody else; Archive notes are included in an .apkg.")
    ap.add_argument("--tag-untagged", action="store_true",
                    help="Add the official band to a listed word that carries no HSK tag")
    ap.add_argument("--prune-non-official", action="store_true",
                    help="Strip every HSK tag from a word the standard does not contain")
    args = ap.parse_args()

    bands = {}
    for e in json.load(open(OFFICIAL, encoding="utf-8")):
        bands.setdefault(e["word"], set()).update(e["levels"])

    col = Collection(args.db)
    try:
        archive = {d.id for d in col.decks.all_names_and_ids() if d.name == "Archive"}

        fixed, skipped_archive = [], 0
        tagged_new, pruned = [], []

        # Notetypes whose field 0 IS the word. ChineseSentences is absent on purpose --
        # see the module docstring. Everything below may only rule on these.
        WORD_NOTETYPES = ("ChineseVocabulary", "ChineseCharacters",
                          "ChineseCharactersWriting")
        word_nt_ids = {m["id"] for m in
                       (col.models.by_name(n) for n in WORD_NOTETYPES) if m}

        def in_scope(note):
            """True if this note may be written, given --include-archive."""
            return args.include_archive or not (
                {c.did for c in note.cards()} <= archive)

        # "tag:HSK", not "tag:HSK::HSK*". This pass both removes a contradicting level and
        # restores a missing one, and a note that is MISSING its level does not match a
        # search for notes that have one. Scoping to HSK::HSK* would make the tool blind
        # to exactly the state it creates.
        for nid in col.find_notes("tag:HSK"):
            note = col.get_note(nid)
            word = strip_html(note.fields[0])
            if not HANZI.match(word) or word not in bands:
                # A word the standard does not contain must carry no HSK tag at all --
                # the bare `HSK` included, since that is itself a claim of membership.
                # Gated on the notetype, never on the shape of the text.
                if (args.prune_non_official and note.mid in word_nt_ids
                        and HANZI.match(word) and in_scope(note)):
                    keep = [t for t in note.tags
                            if t != "HSK" and not t.startswith("HSK::")]
                    if len(keep) != len(note.tags):
                        pruned.append((word, sorted(set(note.tags) - set(keep))))
                        if args.apply:
                            note.tags = keep
                            col.update_note(note)
                continue

            tagged = {m.group(1) for m in (TAG.match(t) for t in note.tags) if m}
            stale = tagged - bands[word]
            if not stale and tagged:
                continue    # every tag it carries is official — nothing to do

            dids = {c.did for c in note.cards()}
            if dids <= archive and not args.include_archive:
                skipped_archive += 1
                continue

            keep = [t for t in note.tags if not (TAG.match(t) and TAG.match(t).group(1) in stale)]

            # Removing is only half of "match the official list". 200 of these notes carry
            # exactly ONE level tag and it is the wrong one (由此看来 tagged 6, official
            # 7-9), so a remove-only pass drops them out of `tag:HSK::*` entirely and they
            # end up claiming no level at all. That is not closer to the reference than a
            # wrong tag -- it is the same defect with no symptom, and resort_main_queue
            # .level_of() then sees None instead of a number.
            #
            # So restore the band. LOWEST, matching the policy the rest of the collection
            # follows: build_hsk30_official.py records `level` as the lowest band because
            # that is where you first meet the word, and every live note here already
            # carries the lowest. Adding the full set instead would make these 199 Archive
            # notes the only ones tagged differently from the 10,289 live ones.
            restored = None
            if not any(TAG.match(t) for t in keep):
                restored = min(bands[word], key=lambda b: (b == "7-9", b))
                keep = keep + [f"HSK::HSK{restored}"]

            fixed.append((word, sorted(bands[word]), sorted(stale), restored))
            if args.apply:
                note.tags = keep
                col.update_note(note)

        # Second pass: listed words carrying no HSK tag at all. They cannot be reached
        # through tag:HSK, so this scans the word notetypes directly.
        if args.tag_untagged:
            for ntname in WORD_NOTETYPES:
                for nid in col.find_notes(f"note:{ntname}"):
                    note = col.get_note(nid)
                    word = strip_html(note.fields[0])
                    if not HANZI.match(word) or word not in bands:
                        continue
                    if any(t == "HSK" or t.startswith("HSK::") for t in note.tags):
                        continue
                    if not in_scope(note):
                        continue
                    band = min(bands[word], key=lambda b: (b == "7-9", b))
                    tagged_new.append((word, band, ntname))
                    if args.apply:
                        note.add_tag(f"HSK::HSK{band}")
                        col.update_note(note)

        for word, band, ntname in tagged_new:
            print(f"  {word:<6} tagged HSK::HSK{band}  ({ntname})")
        for word, removed_tags in pruned:
            print(f"  {word:<6} not in HSK 3.0 — removed {' '.join(removed_tags)}")
        for word, official, removed, restored in fixed:
            what = []
            if removed:
                what.append("removed HSK::HSK" + " HSK::HSK".join(removed))
            if restored:
                what.append(f"restored HSK::HSK{restored}")
            print(f"  {word:<6} official band(s) {'/'.join(official):<8} " + ", ".join(what))
        scope = "live + Archive" if args.include_archive else "live only"
        print(f"\nnotes fixed: {len(fixed)}   (scope: {scope})")
        print(f"listed words newly tagged: {len(tagged_new)}")
        print(f"non-HSK words stripped of HSK tags: {len(pruned)}")
        print(f"Archive-only notes left alone (all suspended): {skipped_archive}")

        if not args.apply:
            print("\nDRY-RUN — nothing written.")
        else:
            # Verify inside the stopped-bot window, as anki_op.sh requires.
            remaining = 0
            # "tag:HSK", not "tag:HSK::HSK*" -- a note this pass stripped bare would
            # silently pass a check that only looks at notes which still carry a level.
            for nid in col.find_notes("tag:HSK"):
                note = col.get_note(nid)
                word = strip_html(note.fields[0])
                if not HANZI.match(word) or word not in bands:
                    continue
                tagged = {m.group(1) for m in (TAG.match(t) for t in note.tags) if m}
                archive_only = {c.did for c in note.cards()} <= archive
                if not (args.include_archive or not archive_only):
                    continue
                if tagged - bands[word] or not tagged:
                    remaining += 1
            print(f"VERIFY: notes still contradicting or missing a level: {remaining}")
            if remaining:
                raise SystemExit("verification failed — tags remain")
    finally:
        col.close()


if __name__ == "__main__":
    main()
