#!/usr/bin/env python3
"""Canonical new-queue ordering for the one study deck. THIS FILE IS THE STRATEGY.

The order is decided nowhere else, so the policy is written here as bands. Each band
beats every band below it, whatever the level or the list position:

  0  `liked`                      a hand mark beats every computed rule
  1  `next::` and `book::`        the set being read NOW beats the curriculum
  2  the curriculum               HSK level ascending, then official-list order
  3  `demoted`                    marked down by hand

Then, across the whole result: each single-character card sits immediately before the
FIRST word that uses it, and characters used by no new word go to the tail.

NO FREQUENCY. Zipf ordered words within a level until 2026-09-01. Vincent removed it;
the curriculum's own order now breaks the tie. That order is the HSK 3.0 list's file
order, which is radical order, so a level arrives grouped by first character.

`book::` moved from the BACK to band 1 the same day. It sat at the back on the reasoning
that those words were being studied elsewhere -- true only while a filtered deck held
them. Once that deck was deleted the tag buried the exact words being read, 1,008 days
out at 8 cards a day.

Supersedes quality/resort_hsk_by_level.py (words only — it would scatter the character
cards, since it repositions every type=0 ord=0 card by word key and a character has no
HSK level tag) and the ad-hoc placement in quality/place_gap_chars.py.

Both decks are handled the same way; HSK7-9's words are all one level, so rule 1 collapses
to plain frequency order there.

Characters used by no *new* word in their own deck (their words are already studied, or the
word lives in the other deck) have no "first usage" to sit before. They go to the tail of
the deck's new queue, ordered by character frequency, and the count is printed. In HSK that
is ~176 cards (漂 帮 努 …, whose words 漂亮/帮助/努力 you finished long ago); in HSK7-9 it is 1 (邦).

Every new ord=0 card in each deck is repositioned (suspended ones too, so their position is
right whenever they are unsuspended). Positions start at 1, step 1.

Usage: bash freq_data/anki_op.sh resort-main freq_data/resort_main_queue.py --apply
       (--db PATH to dry-run against a scratch copy)
"""
import os, re, sys, json, argparse, collections

from anki.collection import Collection

ROOT = "/home/vincent/anki-headless"
sys.path.insert(0, ROOT)
import decks as deck_registry  # noqa: E402
# HSK7-9 was merged into HSK on 2026-09-01, then HSK / Mined / Stella An became `Main`
# the same day. The deck is resolved by ROLE now: a literal here is exactly what made
# the old resort_vocab.py run for months against a deck that had been renamed away.
DECKS = deck_registry.RECOGNITION_DECKS
LEVEL_TAG = re.compile(r"^HSK::HSK([1-6]|7-9)$")
LEVEL_RANK = {**{str(i): i for i in range(1, 7)}, "7-9": 7}


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def rank_of(tags):
    """-2 liked (front), -1 next, 0 normal, 1 demoted, 2 book (very back).

    ONE definition, read by the sort and by the verification below. They disagreed once:
    the check counted level descents across the whole queue, which cannot be zero once
    ranks exist, because every group boundary resets the level. It reported a failure for
    an order that was correct.
    """
    tl = [x.lower() for x in tags]
    if "liked" in tl:
        return -2
    if any(x.startswith(("next::", "book::")) for x in tl):
        # An active set: `next::<name>` is one you chose to pull forward, `book::<title>`
        # is the vocabulary of something you are reading. Both beat the curriculum and
        # neither hard-codes its name here.
        return -1
    return 1 if "demoted" in tl else 0


def level_of(tags, fallback):
    for t in tags:
        m = LEVEL_TAG.match(t)
        if m:
            return LEVEL_RANK[m.group(1)]
    return fallback


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-sync", action="store_true",
                    help="skip the AnkiWeb push after --apply (default: push, so the new "
                         "order reaches your study device before the next session)")
    args = ap.parse_args()

    official = json.load(open(f"{ROOT}/freq_data/hsk30_official.json"))
    hsk = {w["word"]: w["level"] for w in official}
    # Position in the official list, which IS the curriculum's order. A word outside the
    # list has none, so it keeps its current queue position instead (the `due` key below)
    # rather than being given an invented one.
    LIST_POS = {}
    for i, w in enumerate(official):
        LIST_POS.setdefault(w["word"], i)
    OUTSIDE = len(official)
    col = Collection(args.db)
    try:
        cv_id = col.models.by_name("ChineseVocabulary")["id"]
        cc_id = col.models.by_name("ChineseCharacters")["id"]

        for dname in DECKS:
            did = col.decks.id_for_name(dname)
            if did is None:
                print(f"{dname}: missing, skipped"); continue
            # A card borrowed into a filtered deck carries did=<filtered deck> and
            # odid=<this deck>, so the query below cannot see it and its position is left
            # stale. Say so rather than silently resort a subset.
            borrowed = col.db.scalar(
                "SELECT count(*) FROM cards WHERE odid=? AND type=0 AND ord=0", did)
            if borrowed:
                print(f"  WARN {dname}: {borrowed} new cards are on loan to a filtered "
                      f"deck and keep their old positions. Empty that deck first if you "
                      f"want them ordered too.")
            rows = col.db.all(
                "SELECT c.id, c.due, n.sfld, n.mid, n.tags FROM cards c JOIN notes n ON n.id=c.nid "
                "WHERE c.did=? AND c.type=0 AND c.ord=0 ORDER BY c.due, c.id", did)

            words, chars = [], []
            for cid, due, sfld, mid, tags in rows:
                s = strip_html(sfld)
                if mid == cv_id:
                    lvl = level_of(tags.split(), LEVEL_RANK.get(hsk.get(s, ""), 9))
                    # A word tagged 'demoted' (freq overstates its usefulness) sorts to
                    # the very back, whatever its level. Without this the tag is inert:
                    # resort_vocab.py was the only reader of it and its deck is empty.
                    # `book::<title>` means the word is being studied somewhere else --
                    # a filtered deck built on the tag while reading that book. Leaving
                    # such a word in its frequency position double-teaches it, and
                    # front-loading the set is worse: promoting 143 of them by hand once
                    # pushed 绝望 / 悲伤 / 心疼 back by 143 places. The back of the queue
                    # is the right home; the filtered deck introduces them instead, and
                    # once answered they return here as review cards and flow normally.
                    rank = rank_of(tags.split())
                    words.append((rank, lvl, LIST_POS.get(s, OUTSIDE), due, cid, s))
                elif mid == cc_id:
                    chars.append((cid, s, due))
                else:
                    print(f"  WARN {dname}: unexpected notetype for {s!r}, treated as word")
                    words.append((0, 9, OUTSIDE, due, cid, s))

            words.sort(key=lambda t: (t[0], t[1], t[2], t[3]))  # band, level, list pos, current pos
            char_by_glyph = {}
            chars_due = {}
            for cid, s, due in chars:
                char_by_glyph.setdefault(s, []).append(cid)       # dupes impossible today, but be safe
                chars_due.setdefault(s, due)

            order, placed = [], set()
            for rank, lvl, negf, due, cid, w in words:
                for ch in w:                                       # rule 2: char before first use
                    if ch in char_by_glyph and ch not in placed:
                        order.extend(char_by_glyph[ch])
                        placed.add(ch)
                order.append(cid)

            # Characters no new word uses. Ordered by the official list, then by their
            # current position -- the same two keys the words use, for the same reason.
            orphans = sorted((g for g in char_by_glyph if g not in placed),
                             key=lambda g: (LIST_POS.get(g, OUTSIDE), chars_due.get(g, 0)))
            for g in orphans:
                order.extend(char_by_glyph[g])

            assert len(order) == len(rows), f"{dname}: {len(order)} != {len(rows)}"
            assert len(set(order)) == len(order), f"{dname}: duplicate card in order"

            print(f"\n{dname}: {len(words)} words + {len(chars)} chars = {len(rows)} new cards")
            print(f"  chars placed before first use: {len(placed)}   tail (unused by any new word): {len(orphans)}")
            if orphans:
                print(f"  tail chars: {' '.join(orphans[:20])}{' …' if len(orphans) > 20 else ''}")

            if args.apply:
                col.sched.reposition_new_cards(order, starting_from=1, step_size=1,
                                               randomize=False, shift_existing=False)

            # ── verify against the live queue (or the computed order on a dry run) ──
            if args.apply:
                seq = col.db.all(
                    "SELECT n.sfld, n.mid, n.tags FROM cards c JOIN notes n ON n.id=c.nid "
                    "WHERE c.did=? AND c.type=0 AND c.ord=0 ORDER BY c.due, c.id", did)
                seq = [(strip_html(s), m, t) for s, m, t in seq]
                # 1 and 2 hold WITHIN a rank group, never across one. A boundary resets
                # the level by design, so a whole-queue scan reports one false descent per
                # boundary -- 2 of them here, for an order with no real fault.
                desc, bad_f = 0, 0
                for grp in sorted({rank_of(t.split()) for s, m, t in seq if m == cv_id}):
                    prev_l, prev_f = None, None
                    for s, m, t in seq:
                        if m != cv_id or rank_of(t.split()) != grp:
                            continue
                        l = level_of(t.split(), LEVEL_RANK.get(hsk.get(s, ""), 9))
                        f = LIST_POS.get(s, OUTSIDE)
                        if prev_l is not None and l < prev_l:
                            desc += 1
                        # Within a level the official-list position must not go backwards.
                        if prev_l == l and f < prev_f:
                            bad_f += 1
                        prev_l, prev_f = l, f
                # 3. every placed char precedes the first word containing it
                first_word_at, char_at = {}, {}
                for i, (s, m, t) in enumerate(seq):
                    if m == cc_id:
                        char_at.setdefault(s, i)
                    else:
                        for ch in s:
                            first_word_at.setdefault(ch, i)
                late = [ch for ch, i in char_at.items()
                        if ch in first_word_at and i > first_word_at[ch]]
                print(f"  verify: level descents {desc} (want 0) · "
                      f"list-order breaks within level {bad_f} (want 0) · "
                      f"chars after their first word {len(late)} (want 0)")
                if late:
                    print(f"    LATE: {' '.join(late[:20])}")
                head = " ".join(s for s, m, t in seq[:14])
                print(f"  frontmost: {head}")

        print("\nAPPLIED." if args.apply else "\nDRY-RUN — nothing written.")

        # Push to AnkiWeb immediately. Without this the new order sits on the server
        # unsynced until some unrelated later sync, so a study session on the phone in
        # the meantime still serves the OLD order (this is what made the resort look
        # like it "didn't work" — it did, the push just lagged the study session).
        # --db means "run against a scratch copy". Syncing one pushes that COPY's state to
        # AnkiWeb, and the live collection then pulls it down: a test tag on 〇 reached the
        # real collection this way on 2026-08-31. A scratch run never syncs.
        # --db DEFAULTS to the live collection, so `if args.db` is always true. Compare
        # the path: only a DIFFERENT path is a scratch target. The truthiness version of
        # this check silently disabled syncing on real runs too.
        scratch = os.path.abspath(args.db) != os.path.abspath(f"{ROOT}/collection.anki2")
        if scratch and args.apply and not args.no_sync:
            print("SYNC SKIPPED: --db points at a scratch copy; syncing it would push "
                  "that copy to AnkiWeb. Pass --no-sync to silence this.")
        if args.apply and not args.no_sync and not scratch:
            # (os is imported at module level)
            auth_file = os.path.expanduser("~/.anki_auth")
            if not os.path.exists(auth_file):
                print("SYNC SKIPPED: not logged in to AnkiWeb (~/.anki_auth missing). "
                      "The new order is on the server file ONLY — study device will not "
                      "see it until you sync manually.")
            else:
                from anki.sync import SyncAuth
                data = json.load(open(auth_file))
                auth = SyncAuth()
                auth.hkey = data["hkey"]
                if data.get("endpoint"):
                    auth.endpoint = data["endpoint"]
                res = col.sync_collection(auth, sync_media=False)
                if res.new_endpoint:
                    data["endpoint"] = res.new_endpoint
                    json.dump(data, open(auth_file, "w")); os.chmod(auth_file, 0o600)
                # 0=no changes, 1=normal, 2=full sync required
                if res.required == 2:
                    print("SYNC: *** FULL SYNC REQUIRED *** — the new order was NOT uploaded. "
                          "Resolve with `anki-cli sync` (upload), THEN sync your device down.")
                else:
                    print(f"SYNC: pushed to AnkiWeb (status={res.required}). "
                          "Now sync your study device DOWN before your next session.")
    finally:
        col.close()


if __name__ == "__main__":
    main()
