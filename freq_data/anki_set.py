#!/usr/bin/env python3
"""Set operations on cards chosen by an Anki search query.

WHY THIS EXISTS. On 2026-09-01 ten one-off scripts were written in a day for operations
that differ only in the SET of cards they touch. Four of them (untag, edit a field,
delete by id, delete a deck's leftovers) duplicated `anki-cli` and the bot's tools. The
rest existed only because nothing could reposition a queue or move a deck from a query.

AND THE BUG THEY ALL SHARED: each scoped itself by a guess about the data's shape --
"the ChineseVocabulary notetype", "fields named *inyin*", "the HSK deck" -- and each
missed the rows that did not fit the guess. A purge that iterated one notetype left 431
character notes behind; a pinyin fix that read one field name left 51 cards showing
numeric pinyin. Here the scope is an Anki SEARCH, evaluated by Anki, so it covers every
notetype and deck that actually matches.

Every subcommand: dry-run by default, prints what it matched, verifies after writing.

  bash freq_data/anki_op.sh setop freq_data/anki_set.py move   "deck:non-HSK tag:x" --to Mined --apply
  bash freq_data/anki_op.sh setop freq_data/anki_set.py tag    "deck:HSK 焦虑" --tag liked --apply
  bash freq_data/anki_op.sh setop freq_data/anki_set.py untag  "tag:liked" --tag liked --apply
  bash freq_data/anki_op.sh setop freq_data/anki_set.py suspend   "deck:Archive" --apply
  bash freq_data/anki_op.sh setop freq_data/anki_set.py unsuspend "tag:liked" --apply
  bash freq_data/anki_op.sh setop freq_data/anki_set.py front  "tag:liked deck:HSK" --apply
  bash freq_data/anki_op.sh setop freq_data/anki_set.py back   "tag:demoted" --apply
  bash freq_data/anki_op.sh setop freq_data/anki_set.py byfreq "deck:Mined is:new" --apply
  bash freq_data/anki_op.sh setop freq_data/anki_set.py delete "deck:non-HSK -is:review" --apply
  bash freq_data/anki_op.sh setop freq_data/anki_set.py replace "deck:Main" \
      --field Meaning --pattern '\bsth\b\.?' --with something --apply

`replace` edits ONE NAMED FIELD by regex, across whatever the query matches. It skips a
note whose notetype has no field of that name and prints how many it skipped, rather than
guessing an index: field 2 is `Meaning` on ChineseVocabulary AND on ChineseCharacters, but
field 5 on the xiehanzi import notetypes is a rendered HTML blob. An index would have
rewritten 44,168 archived blobs. Names are checked per note, so the scope stays honest.
"""
import argparse
import re
import sys

from anki.collection import Collection

COL = "/home/vincent/anki-headless/collection.anki2"
# Deleting is the only irreversible op here; it refuses to run over a set this large
# unless --force is given, so a typo'd query cannot wipe the collection.
DELETE_CAP = 12000


def word_of(col, cid):
    n = col.get_note(col.get_card(cid).nid)
    return re.sub(r"<[^>]+>", "", n.fields[0]).strip()


def show(col, cids, label, limit=12):
    print(f"{label}: {len(cids)} card(s)")
    for cid in cids[:limit]:
        c = col.get_card(cid)
        print(f"   {word_of(col, cid)[:16]:16s} {col.decks.name(c.did):10s} "
              f"queue={c.queue} type={c.type}")
    if len(cids) > limit:
        print(f"   ... and {len(cids) - limit} more")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("op", choices=["move", "tag", "untag", "suspend", "unsuspend",
                                   "front", "back", "byfreq", "delete", "count",
                                   "replace"])
    ap.add_argument("query", help="an Anki search, e.g. 'deck:HSK tag:liked is:new'")
    ap.add_argument("--to", help="destination deck (move)")
    ap.add_argument("--tag", help="tag to add or remove")
    ap.add_argument("--field", help="field NAME to edit (replace)")
    ap.add_argument("--pattern", help="regex to find (replace)")
    ap.add_argument("--with", dest="repl", help="replacement text (replace)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="allow a delete larger than the safety cap")
    ap.add_argument("--db", default=COL)
    args = ap.parse_args()

    col = Collection(args.db)
    try:
        cids = list(col.find_cards(args.query))
        print(f"query {args.query!r}")
        show(col, cids, "matched")
        if not cids:
            print("nothing matched — check the query")
            return
        if args.op == "count":
            return

        if args.op in ("front", "back", "byfreq"):
            new = [c for c in cids if col.get_card(c).type == 0]
            if len(new) != len(cids):
                print(f"note: {len(cids) - len(new)} matched card(s) are not new; "
                      f"only the {len(new)} new ones can be repositioned")
            cids = new
            if not cids:
                return

        if args.op == "delete" and len(cids) > DELETE_CAP and not args.force:
            sys.exit(f"refusing: {len(cids)} cards is over the {DELETE_CAP} cap. "
                     f"Narrow the query, or pass --force if you mean it.")

        if args.op == "replace":
            if not (args.field and args.pattern and args.repl is not None):
                sys.exit("replace needs --field, --pattern and --with")
            rx = re.compile(args.pattern)
            # Preview BEFORE the dry-run exit, so a dry run shows the actual rewrites.
            # A replace that prints only a count is unreviewable, and this one edits the
            # text that appears on the card.
            edits, no_field = [], 0
            for nid in sorted({col.get_card(c).nid for c in cids}):
                note = col.get_note(nid)
                names = [f["name"] for f in note.note_type()["flds"]]
                if args.field not in names:
                    no_field += 1
                    continue
                i = names.index(args.field)
                before = note.fields[i]
                after = rx.sub(args.repl, before)
                if after != before:
                    edits.append((nid, i, before, after))
            print(f"\nreplace in field {args.field!r}: {len(edits)} note(s) change, "
                  f"{no_field} skipped (notetype has no such field)")
            for nid, i, before, after in edits[:15]:
                print(f"   - {before[:72]}\n   + {after[:72]}")
            if len(edits) > 15:
                print(f"   ... and {len(edits) - 15} more")
            if not args.apply:
                print("\nDRY-RUN (pass --apply)")
                return
            for nid, i, before, after in edits:
                note = col.get_note(nid)
                note.fields[i] = after
                col.update_note(note)
            bad = [nid for nid, i, _, after in edits if col.get_note(nid).fields[i] != after]
            left = sum(1 for nid, i, _, _ in edits if rx.search(col.get_note(nid).fields[i]))
            print(f"\nreplace: {len(edits)} note(s) written, {len(bad)} failure(s), "
                  f"{left} still matching the pattern (want 0)")
            assert not bad and not left, (bad[:8], left)
            print("APPLIED")
            return

        if not args.apply:
            print("\nDRY-RUN (pass --apply)")
            return

        nids = sorted({col.get_card(c).nid for c in cids})
        if args.op == "move":
            did = col.decks.id_for_name(args.to)
            if did is None:
                sys.exit(f"no deck named {args.to!r}")
            col.set_deck(cids, did)
            bad = [c for c in cids if col.get_card(c).did != did]
        elif args.op in ("tag", "untag"):
            if not args.tag:
                sys.exit("--tag is required")
            for nid in nids:
                n = col.get_note(nid)
                have = [t.lower() for t in n.tags]
                if args.op == "tag" and args.tag.lower() not in have:
                    n.tags.append(args.tag)
                    col.update_note(n)
                elif args.op == "untag" and args.tag.lower() in have:
                    n.tags = [t for t in n.tags if t.lower() != args.tag.lower()]
                    col.update_note(n)
            bad = [n for n in nids
                   if (args.tag.lower() in [t.lower() for t in col.get_note(n).tags])
                   != (args.op == "tag")]
        elif args.op in ("suspend", "unsuspend"):
            (col.sched.suspend_cards if args.op == "suspend"
             else col.sched.unsuspend_cards)(cids)
            want = -1 if args.op == "suspend" else 0
            bad = [c for c in cids
                   if (col.get_card(c).queue == -1) != (args.op == "suspend")]
        elif args.op in ("front", "back", "byfreq"):
            from wordfreq import zipf_frequency
            by_deck = {}
            for cid in cids:
                by_deck.setdefault(col.get_card(cid).did, []).append(cid)
            for did, group in by_deck.items():
                if args.op == "byfreq":
                    group.sort(key=lambda c: -zipf_frequency(word_of(col, c), "zh"))
                    start = 1
                else:
                    lo = col.db.scalar("SELECT MIN(due) FROM cards WHERE did=? "
                                       "AND type=0 AND ord=0", did) or 1
                    hi = col.db.scalar("SELECT MAX(due) FROM cards WHERE did=? "
                                       "AND type=0 AND ord=0", did) or 1
                    start = lo - len(group) if args.op == "front" else hi + 1
                for i, cid in enumerate(group):
                    c = col.get_card(cid)
                    c.due = start + i
                    col.update_card(c)
            bad = []
        elif args.op == "delete":
            col.remove_notes(nids)
            bad = [n for n in nids
                   if col.db.scalar("SELECT count(*) FROM notes WHERE id=?", n)]

        print(f"\n{args.op}: {len(cids)} card(s) / {len(nids)} note(s), "
              f"{len(bad)} failure(s)")
        assert not bad, bad[:8]
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
