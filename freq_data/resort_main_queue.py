#!/usr/bin/env python3
"""Canonical new-queue ordering for the one study deck. THIS FILE IS THE STRATEGY.

The order is decided nowhere else, so the policy is written here as bands. Each band
beats every band below it, whatever the level or the list position:

  0  `set::emotions`              the hand-picked priority set beats every computed rule
  1  `next::`                     the handful you chose to pull forward right now
  2  the curriculum               HSK level ascending, then official-list order
     `later::business`            later within its own HSK level, never after later levels
     `queue::post-hsk5`           selected words immediately after HSK5, before HSK6
     `after::HSK5`               Stella targets mixed 3-for-3 with HSK7–9
  3  `demoted`                    marked down by hand

There is no fourth band for "everything else". A word outside the HSK 3.0 list gets level
9 from level_of(), and level 9 sorts after HSK 7-9 (rank 7) inside band 2. Stella words
tagged `after::HSK5` join the HSK 7-9 tier; unanchored non-syllabus words, including
the rest of a book and `set::connectives`, follow every HSK level.

Band 0 read `liked` until 2026-09-04. The tag claimed to be a hand mark and was not: a
single run of order_study_sets.py wrote all 40 of them at 16:34 on 2026-09-01. Vincent
asked for the tag to go. `set::emotions` now IS the front set, one word per emotional
category, and order_study_sets.py moves everything it defers to `set::emotions-later`.
Match the tag EXACTLY: `set::emotions-later`, `set::connectives` and `set::stella-an` are
deliberately not band 0, so a prefix test on `set::` would pull extra notes forward.

`book::` LEFT band 1 on 2026-09-04. It joined that band three days earlier, when the tag
meant a book you were reading and the set was small. 《黑暗森林》 made it 575 cards, which
is 72 days at 8 new/day standing in front of the curriculum, and most of a book's
vocabulary arrives long after you finish the book. Vincent picked 5 words instead, tagged
`next::黑暗森林`. The other 570 rejoin the curriculum at their own HSK level, and the
non-HSK part of them lands after every HSK level, by the level-9 rule above. `book::`
stays as the set's LABEL -- it is how the dashboard draws the row -- it just no longer
carries an order.

Then, across the whole result: each single-character card sits immediately before the
FIRST word that uses it.

TWO RULES ABOUT CHARACTERS, both added 2026-09-19.

1. `Hanly gap` characters at or below HSK 5 are INTERLEAVED, one every 5 cards that Anki
   will actually serve. Vincent studies 15-25 new cards a day, so that is five characters
   in a 25-card day. There are 105 of them and the interleave ends at visible position
   525. A character Hanly taught needs no card and does not have one, so the export at
   HANLY_EXPORT selects the set; the filter is a no-op today and exists so a newer export
   drops anything Hanly adds.

2. A character no new word uses no longer goes to the TAIL. It sorts into the curriculum
   at its own HSK level, like a word. The tail was an artefact of rule 2 above: whether a
   character had an unstudied word to sit before said nothing about how useful it is.
   俩 倍 县 棵 盐 逛 sat at positions 7,887 to 7,892, about 525 days out at 15 a day,
   while 涨 岸 毒 闲 sat inside the first 105.

3. A character tagged `hanly-gap` is an explicit vocabulary target, not a component aid.
   It sorts at its own HSK level just like a word. Otherwise a failed HSK 2 character can
   be delayed until the first unseen HSK 7-9 word containing it, defeating the migration.

SUSPENDED new cards still get a position, so the order is right whenever they are
unsuspended, but they do NOT count toward the interleave. Anki skips them when serving, so
a suspended card in an interleave slot would steal a character Vincent never sees. 284 sit
in Main today and 〇 was one of them.

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
#: A single CJK character. The interleaved set is characters, never words.
HANZI_CHAR = re.compile(r"[\u4e00-\u9fff\u3007]")
#: HSK ceiling for the interleaved character set, and how often one appears.
#: 5 and 5 give five characters in every twenty-five cards, which is Vincent's day.
PRIORITY_MAX_LEVEL = LEVEL_RANK["5"]
INTERLEAVE_EVERY = 5
#: Hanly's own export. A character in it needs no card and has none, so this filter is a
#: no-op today; it is here so a newer export automatically drops anything Hanly adds.
HANLY_EXPORT = f"{ROOT}/learning_progress_export_2026-08-04T12-06-51.893265.json"


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def rank_of(tags):
    """-2 the emotion set (front), -1 next, 0 the curriculum, 1 demoted.

    ONE definition, read by the sort and by the verification below. They disagreed once:
    the check counted level descents across the whole queue, which cannot be zero once
    ranks exist, because every group boundary resets the level. It reported a failure for
    an order that was correct.
    """
    tl = [x.lower() for x in tags]
    if "set::emotions" in tl:
        # Exact match, never a prefix. `set::emotions-later` is the deferred half of the
        # same set and belongs in the curriculum band.
        return -2
    if any(x.startswith("next::") for x in tl):
        # `next::<name>` is a set you chose to pull forward NOW. Keep it small: whatever
        # is here jumps the whole curriculum. `book::` is deliberately absent -- see the
        # module docstring. The prefix means the name is not hard-coded here.
        return -1
    return 1 if "demoted" in tl else 0


def level_of(tags, fallback):
    for t in tags:
        m = LEVEL_TAG.match(t)
        if m:
            return LEVEL_RANK[m.group(1)]
    return fallback


def placement_level(tags, curriculum_level):
    """Place selected words after HSK5, or the Stella lane alongside HSK7–9."""
    lower = {t.lower() for t in tags}
    if "queue::post-hsk5" in lower:
        return 5.5
    return 7 if "after::hsk5" in lower else curriculum_level


def within_level_rank(tags):
    """Keep specialized material late in its level without breaking HSK progression."""
    return 1 if "later::business" in {tag.lower() for tag in tags} else 0


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
    try:
        hanly_taught = {c for c in json.load(open(HANLY_EXPORT))
                        if HANZI_CHAR.fullmatch(c)}
    except FileNotFoundError:
        hanly_taught = set()
        print(f"WARN: no Hanly export at {HANLY_EXPORT}; interleaving every character "
              f"at or below HSK {PRIORITY_MAX_LEVEL}")
    frequency_path = f'{ROOT}/freq_data/stella_frequency.json'
    stella_frequency = json.load(open(frequency_path))
    col = Collection(args.db)
    try:
        cv_id = col.models.by_name("ChineseVocabulary")["id"]
        cc_id = col.models.by_name("ChineseCharacters")["id"]

        def curriculum_entry(mid, tags):
            return mid == cv_id or (mid == cc_id and "hanly-gap" in
                                    {tag.lower() for tag in tags})

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
                "SELECT c.id, c.due, n.sfld, n.mid, n.tags, c.queue FROM cards c "
                "JOIN notes n ON n.id=c.nid "
                "WHERE c.did=? AND c.type=0 AND c.ord=0 ORDER BY c.due, c.id", did)

            words, chars, priority = [], [], []
            hsk79_ids, stella_ids, word_ids = set(), set(), set()
            suspended = set()
            for cid, due, sfld, mid, tags, queue in rows:
                s = strip_html(sfld)
                tl = tags.split()
                if queue == -1:
                    # A suspended new card still gets a position, so the order is right
                    # whenever it is unsuspended. It must NOT count toward the interleave:
                    # Anki skips it when serving, so a suspended card in an interleave slot
                    # steals a character Vincent never sees. 284 sit in Main today, and 〇
                    # is one of them.
                    suspended.add(cid)
                lvl = level_of(tl, LEVEL_RANK.get(hsk.get(s, ""), 9))
                # The interleaved set: one Chinese character, at or below
                # PRIORITY_MAX_LEVEL, that Hanly never taught. Vincent reads characters
                # already, so a character Hanly covered needs no card and does not have
                # one. These do, and before 2026-09-19 they sat wherever rule 2 or the
                # orphan tail dropped them -- 俩 倍 县 棵 盐 逛 were at positions 7,887 to
                # 7,892, about 525 days out, while 涨 岸 毒 闲 sat inside the first 105.
                # Their position depended on whether some unstudied word happened to
                # contain them, which says nothing about how useful the character is.
                if len(s) == 1 and HANZI_CHAR.fullmatch(s) and lvl <= PRIORITY_MAX_LEVEL \
                        and s not in hanly_taught and queue != -1 \
                        and "hanly-gap" not in {tag.lower() for tag in tl}:
                    priority.append((lvl, LIST_POS.get(s, OUTSIDE), due, cid, s))
                    continue
                if mid == cv_id:
                    word_ids.add(cid)
                if curriculum_entry(mid, tl) and rank_of(tl) == 0:
                    if 'queue::post-hsk5' in {t.lower() for t in tl}:
                        pass
                    elif 'after::hsk5' in {t.lower() for t in tl}:
                        stella_ids.add(cid)
                    elif lvl == 7:
                        hsk79_ids.add(cid)
                if curriculum_entry(mid, tl):
                    # A word tagged 'demoted' (freq overstates its usefulness) sorts to
                    # the very back, whatever its level. Without this the tag is inert:
                    # resort_vocab.py was the only reader of it and its deck is empty.
                    # rank_of IS the rule; do not restate it here.
                    words.append((rank_of(tl), placement_level(tl, lvl), within_level_rank(tl),
                                  LIST_POS.get(s, OUTSIDE), due, cid, s))
                elif mid == cc_id:
                    chars.append((cid, s, due, lvl))
                else:
                    print(f"  WARN {dname}: unexpected notetype for {s!r}, treated as word")
                    words.append((rank_of(tl), placement_level(tl, 9), within_level_rank(tl), OUTSIDE, due, cid, s))

            priority.sort(key=lambda t: (t[0], t[1], t[2]))   # level, list pos, current pos

            # Rule 2 needs the glyphs the remaining words actually contain. A character
            # no word uses has nothing to sit before. Until 2026-09-19 those went to the
            # very tail, behind every word in the collection. They now sort into the
            # curriculum at their own HSK level, like a word, because the tail position
            # was an artefact of the rule and not a judgement about the character.
            used = {ch for *_, w in words for ch in w}
            char_by_glyph, chars_due = {}, {}
            for cid, s, due, lvl in chars:
                if s in used:
                    char_by_glyph.setdefault(s, []).append(cid)
                    chars_due.setdefault(s, due)
                else:
                    words.append((0, lvl, 0, LIST_POS.get(s, OUTSIDE), due, cid, s))

            words.sort(key=lambda t: (t[0], t[1], t[2], t[3], t[4]))
            # band, level, within-level priority, official-list position, current position

            # Mix vocabulary in visible blocks; suspended cards do not consume slots.
            hsk_lane = [t for t in words if t[5] in hsk79_ids]
            stella_lane = [t for t in words if t[5] in stella_ids]
            stella_lane.sort(key=lambda t: (-stella_frequency.get(t[6],{}).get('videos',0),
                                           -stella_frequency.get(t[6],{}).get('count',0), t[4], t[5]))
            mixed = []
            hi = si = 0
            while hi < len(hsk_lane) and si < len(stella_lane):
                for lane, which in ((hsk_lane, 'hsk'), (stella_lane, 'stella')):
                    at = hi if which == 'hsk' else si
                    served = 0
                    while at < len(lane) and served < 3:
                        entry = lane[at]; mixed.append(entry); at += 1
                        served += entry[5] not in suspended and entry[5] in word_ids
                    if which == 'hsk': hi = at
                    else: si = at
            mixed.extend(hsk_lane[hi:]); mixed.extend(stella_lane[si:])
            if mixed:
                first = next(i for i,t in enumerate(words) if t[5] in hsk79_ids | stella_ids)
                prefix = [t for t in words[:first] if t[5] not in hsk79_ids | stella_ids]
                suffix = [t for t in words[first:] if t[5] not in hsk79_ids | stella_ids]
                words = prefix + mixed + suffix
            # Check the visible word-lane pattern independently of character insertions.
            actual = ['H' if t[5] in hsk79_ids else 'S' for t in mixed if t[5] not in suspended and t[5] in word_ids]
            nh = sum(c=='H' for c in actual); ns = sum(c=='S' for c in actual)
            expected=[]; rh,rs=nh,ns
            while rh and rs:
                n=min(3,rh);expected.extend(['H']*n);rh-=n
                n=min(3,rs);expected.extend(['S']*n);rs-=n
            expected.extend(['H']*rh);expected.extend(['S']*rs)
            assert actual == expected, 'Stella/HSK7-9 block verification failed'
            print(f'  3-for-3 blend: {nh} HSK7-9 words, {ns} Stella words; visible block pattern verified')

            base, placed = [], set()
            for rank, lvl, later, list_pos, due, cid, w in words:
                for ch in w:                                       # rule 2: char before first use
                    if ch in char_by_glyph and ch not in placed:
                        base.extend(char_by_glyph[ch])
                        placed.add(ch)
                base.append(cid)

            # Interleave: one priority character every INTERLEAVE_EVERY cards, until the
            # set runs out. At 25 new cards a day that is 5 characters and 20 words.
            # `visible` counts only the cards Anki will actually serve, so the ratio is
            # 5 per 25 STUDIED cards rather than 5 per 25 queue slots.
            order, pri_at, visible = [], [], 0
            pi = bi = 0
            while pi < len(priority) or bi < len(base):
                take_priority = pi < len(priority) and (visible % INTERLEAVE_EVERY
                                                        == INTERLEAVE_EVERY - 1)
                if take_priority or bi >= len(base):
                    if pi < len(priority):
                        pri_at.append(len(order))
                        order.append(priority[pi][3]); pi += 1
                        visible += 1
                    else:
                        cid = base[bi]; bi += 1
                        order.append(cid)
                        visible += cid not in suspended
                else:
                    cid = base[bi]; bi += 1
                    order.append(cid)
                    visible += cid not in suspended


            assert len(order) == len(rows), f"{dname}: {len(order)} != {len(rows)}"
            assert len(set(order)) == len(order), f"{dname}: duplicate card in order"

            print(f"\n{dname}: {len(words)} entries + {len(chars)} chars "
                  f"+ {len(priority)} interleaved = {len(rows)} new cards")
            print(f"  chars placed before first use: {len(placed)}")
            print(f"  interleaved 1-in-{INTERLEAVE_EVERY} up to HSK {PRIORITY_MAX_LEVEL}: "
                  f"{len(priority)} chars, last one at position "
                  f"{pri_at[-1] + 1 if pri_at else 0}")
            if priority:
                print(f"  interleaved: {' '.join(t[4] for t in priority[:24])}"
                      f"{' …' if len(priority) > 24 else ''}")

            if args.apply:
                col.sched.reposition_new_cards(order, starting_from=1, step_size=1,
                                               randomize=False, shift_existing=False)

            # ── verify against the live queue (or the computed order on a dry run) ──
            if args.apply:
                seq = col.db.all(
                    "SELECT n.sfld, n.mid, n.tags, c.queue FROM cards c "
                    "JOIN notes n ON n.id=c.nid "
                    "WHERE c.did=? AND c.type=0 AND c.ord=0 ORDER BY c.due, c.id", did)
                seq = [(strip_html(s), m, t, q) for s, m, t, q in seq]
                live_ids = [r[0] for r in col.db.all('SELECT id FROM cards WHERE did=? AND type=0 AND ord=0 ORDER BY due,id', did)]
                assert live_ids == order, 'Live queue differs from verified computed order'
                # 1 and 2 hold WITHIN a rank group, never across one. A boundary resets
                # the level by design, so a whole-queue scan reports one false descent per
                # boundary -- 2 of them here, for an order with no real fault.
                # The interleaved characters sit OUTSIDE the curriculum order on
                # purpose, so they are excluded from checks 1-3. Check 4 covers them.
                pri_set = {t[4] for t in priority}
                desc, bad_f = 0, 0
                for grp in sorted({rank_of(t.split()) for s, m, t, q in seq
                                   if curriculum_entry(m, t.split())}):
                    prev_l, prev_w, prev_f = None, None, None
                    for s, m, t, q in seq:
                        if not curriculum_entry(m, t.split()) \
                                or rank_of(t.split()) != grp or s in pri_set \
                                or 'after::hsk5' in {tag.lower() for tag in t.split()}:
                            continue
                        l = placement_level(t.split(), level_of(t.split(), LEVEL_RANK.get(hsk.get(s, ""), 9)))
                        w = within_level_rank(t.split())
                        f = LIST_POS.get(s, OUTSIDE)
                        if prev_l is not None and l < prev_l:
                            desc += 1
                        # Specialized cards may reset list order once within the same
                        # level, but may never jump back into the general subgroup.
                        if prev_l == l and w < prev_w:
                            bad_f += 1
                        if prev_l == l and w == prev_w and f < prev_f:
                            bad_f += 1
                        prev_l, prev_w, prev_f = l, w, f
                # 3. every placed char precedes the first word containing it
                first_word_at, char_at = {}, {}
                for i, (s, m, t, q) in enumerate(seq):
                    if s in pri_set:
                        continue
                    if m == cc_id:
                        if not curriculum_entry(m, t.split()):
                            char_at.setdefault(s, i) # explicit hanly-gap targets follow curriculum
                    else:
                        for ch in s:
                            first_word_at.setdefault(ch, i)
                late = [ch for ch, i in char_at.items()
                        if ch in first_word_at and i > first_word_at[ch]]
                # 4. the interleave itself: one priority card every INTERLEAVE_EVERY
                # slots, until the set is exhausted, and none of them left behind.
                vis = [(s, m, t) for s, m, t, q in seq if q != -1]
                at = [i for i, (s, m, t) in enumerate(vis) if s in pri_set]
                want = list(range(INTERLEAVE_EVERY - 1,
                                  INTERLEAVE_EVERY * len(pri_set), INTERLEAVE_EVERY))
                spacing_ok = at == want[:len(at)] and len(at) == len(pri_set)
                print(f"  verify: level descents {desc} (want 0) · "
                      f"list-order breaks within level {bad_f} (want 0) · "
                      f"chars after their first word {len(late)} (want 0)")
                print(f"  verify: interleave {len(at)}/{len(pri_set)} placed, "
                      f"spacing {'ok' if spacing_ok else 'WRONG'} "
                      f"(every {INTERLEAVE_EVERY}th slot to position "
                      f"{at[-1] + 1 if at else 0})")
                if late:
                    print(f"    LATE: {' '.join(late[:20])}")
                assert desc == 0 and bad_f == 0 and not late and spacing_ok, "Queue verification failed"
                head = " ".join(s for s, m, t, q in seq if q != -1)
                print(f"  frontmost (unsuspended): {' '.join(head.split()[:14])}")

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
