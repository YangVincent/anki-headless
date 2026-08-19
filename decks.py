"""The deck list, expressed as roles rather than names.

Every place that needed "the decks I study" used to spell the names out. They appeared in
six separate tuples across three files, plus two sibling repositories, and each one was a
place a rename could go silently wrong. That is exactly what happened, four times over:
`Vocab`, `hanly`, `hanly-reverse` and `Knowledge::Languages::Chinese::Vocabulary` all
stopped resolving, and the code that named them ran for months doing nothing.

**Change a deck name HERE and nothing else needs editing.** Nothing outside this module
should contain a deck-name literal.

Roles, not names, is the point. A caller wants "where do new words go", not "Mined". If
the deck is renamed, the role does not move.
"""

from dataclasses import dataclass, field

# ── roles ─────────────────────────────────────────────────────────────
RECOGNITION = "recognition"   # ord 0 lives here; "studying a word" means studying these
PRODUCTION = "production"     # ord 1 `English-Speaking`, maturity-gated
CLOZE = "cloze"               # ord 2 `Cloze-Recall`, maturity-gated
ARCHIVE = "archive"           # parked; always suspended; never studied
RESERVED = "reserved"         # Anki's own deck 1, which cannot be deleted


@dataclass(frozen=True)
class Deck:
    name: str
    role: str
    #: which maturity gates count this deck as a source of "the word is known"
    gates: tuple = ()
    #: newly created vocabulary notes are filed here
    new_words: bool = False
    #: earlier names for this deck, kept so a check is correct against an old backup
    legacy_names: tuple = ()
    note: str = ""


# ── the list ──────────────────────────────────────────────────────────
# Consolidated 2026-08-19, down from 26 decks. This is the whole collection.
DECKS = (
    Deck("HSK", RECOGNITION, gates=(PRODUCTION, CLOZE),
         note="HSK 3.0 levels 1-6. Single-character words excluded (studied in Hanly)."),
    Deck("HSK7-9", RECOGNITION, gates=(PRODUCTION, CLOZE),
         note="HSK 7-9."),
    Deck("non-HSK", RECOGNITION, gates=(PRODUCTION, CLOZE),
         note="Frequency-ordered vocabulary outside HSK 3.0."),
    # Mined is a CLOZE source but not a PRODUCTION one. That asymmetry is a deliberate
    # choice, not an oversight -- and writing it here is what makes it visible. Its
    # consequence: all 446 production cards for mined words are unreleasable, wherever
    # they sit (249 in Reverse, 197 still in Archive). Counting only the ones already in
    # Reverse understated it.
    Deck("Mined", RECOGNITION, gates=(CLOZE,), new_words=True,
         note="Words added from anywhere that are not in HSK. New arrivals go to the front."),
    Deck("Reverse", PRODUCTION,
         note="Production cards. Filled and suspended by the maturity gate, not by hand."),
    Deck("Cloze", CLOZE, legacy_names=("Vocab Cloze",),
         note="Cloze cards. Filled and suspended by the maturity gate, not by hand."),
    Deck("Archive", ARCHIVE, legacy_names=("Hidden",),
         note="Everything parked. Always suspended (0 of 213,434 live). 111,925 notes "
              "have every card here; 66,382 of those are the user's own vocabulary, "
              "character and sentence notes, which must be promoted, never re-created."),
    Deck("Default", RESERVED,
         note="0 cards. Anki reserves deck id 1 and will not let it be deleted."),
)

BY_NAME = {d.name: d for d in DECKS}
ALL_NAMES = tuple(d.name for d in DECKS)


def _named(role):
    return tuple(d.name for d in DECKS if d.role == role)


def _one(role):
    names = _named(role)
    if len(names) != 1:
        raise ValueError(f"expected exactly one {role!r} deck, found {names}")
    return names[0]


# ── derived views. Import these, never a literal. ─────────────────────
RECOGNITION_DECKS = _named(RECOGNITION)
PRODUCTION_DECK = _one(PRODUCTION)
CLOZE_DECK = _one(CLOZE)
ARCHIVE_DECK = _one(ARCHIVE)

#: The archive under every name it has had. A check that reads only the current name is
#: wrong during a rename and wrong against any older backup.
ARCHIVE_NAMES = (ARCHIVE_DECK,) + BY_NAME[ARCHIVE_DECK].legacy_names

#: Decks the user actually studies from — everything except the archive and Anki's own.
STUDY_DECKS = tuple(d.name for d in DECKS if d.role not in (ARCHIVE, RESERVED))

#: Decks a TOOL may file or move a card into. Narrower than ALL_NAMES, which only says a
#: deck is declared. `Reverse` and `Cloze` are owned by the maturity gate — a hand-move
#: into either is immediately undone or, worse, survives ungated. `Default` is Anki's own
#: and the collection keeps it empty.
#: NOT the archive. A card moved there by hand stays unsuspended -- the deck's whole
#: contract is "always suspended" -- and its production and cloze siblings land where no
#: gate will look for them again, because a parked immature card is exactly what the gate
#: is built to leave alone. Parking is the gate's job, or an explicit script's.
WRITABLE_DECKS = tuple(d.name for d in DECKS if d.role == RECOGNITION)

#: Decks that must exist for the bot to work. Only `Default` is excluded, because Anki
#: guarantees it. The ARCHIVE belongs here: its absence is the one that causes a
#: destructive write, and it was silently exempt.
REQUIRED_DECKS = STUDY_DECKS + (ARCHIVE_DECK,)

#: Where a newly created vocabulary note is filed. Checked like a role: a bare
#: StopIteration at import time says nothing, and two such decks used to pick the first
#: without a word.
_new_words = [d.name for d in DECKS if d.new_words]
if len(_new_words) != 1:
    raise ValueError(f"expected exactly one deck with new_words=True, found {_new_words}")
NEW_WORDS_DECK = _new_words[0]


def gate_sources(gate):
    """Deck NAMES whose ord-0 card counts as "the user knows this word", for one gate.

    Prefer gate_source_ids(). This exists for display and for Anki search strings.
    """
    return tuple(d.name for d in DECKS if gate in d.gates)


def is_archive(name):
    """True for the archive deck under any of its names, or a subdeck of one.

    Name-based because it is fed raw rows from the `decks` table. Prefer archive_ids().
    """
    return any(name == a or name.startswith(a + "::") or name.startswith(a + "\x1f")
               for a in ARCHIVE_NAMES)


# ── resolving a ROLE against a collection ─────────────────────────────
# Callers ask for a role and receive deck IDs. A deck NAME does not cross this boundary.
#
# Three places genuinely need a name, and only those three:
#   * Anki's search syntax, which is textual: `deck:HSK`
#   * anything the user or the model reads or types
#   * the /api/stats HTTP contract, which is published in terms of names
# Everything else takes ids. The `*_name` helpers below are marked for that reason; using
# one anywhere else re-creates the coupling this module exists to remove.


class DeckMissing(RuntimeError):
    """A deck declared in DECKS does not exist in the collection."""


def _subtree_ids(col, name):
    """Deck ids for `name` and its subdecks. Empty if the deck does not exist.

    Resolution goes through Anki's own id_for_name, which is case-insensitive and
    NFC-normalising, then subdecks are matched against the CANONICAL name it returns.
    A plain `==` disagreed with it: `id_for_name('hsk')` resolved while `== 'HSK'` did
    not, so the startup health check called the collection healthy while the gate
    refused to run on the same deck. Three code paths must not give three answers to
    "does this deck exist".
    """
    did = col.decks.id_for_name(name)
    if did is None:
        return []
    canonical = col.decks.name(did)
    return [d.id for d in col.decks.all_names_and_ids()
            if d.id == did or d.name.startswith(canonical + "::")]


def deck_ids_for(col, role):
    """Deck IDs for every deck holding `role`, subdecks included.

    Raises DeckMissing rather than returning a short list. A silently short list is how
    `Mined` lost its subdecks from the maturity query and how a renamed source deck let
    the gate act on half the data.
    """
    ids, missing = [], []
    for d in DECKS:
        if d.role != role:
            continue
        found = _subtree_ids(col, d.name)
        ids.extend(found) if found else missing.append(d.name)
    if missing:
        raise DeckMissing(f"{role} deck(s) missing from the collection: "
                          + ", ".join(repr(n) for n in missing))
    if not ids:
        raise DeckMissing(f"no deck declared with role {role!r}")
    return ids


def deck_id_for(col, role):
    """The one deck ID for a single-deck role (production, cloze, archive)."""
    names = _named(role)
    if len(names) != 1:
        raise ValueError(f"role {role!r} covers {len(names)} decks; use deck_ids_for()")
    did = col.decks.id_for_name(names[0])
    if did is None:
        raise DeckMissing(f"no deck named {names[0]!r}")
    return did


def new_words_deck_id(col):
    """Where a newly created vocabulary note is filed."""
    did = col.decks.id_for_name(NEW_WORDS_DECK)
    if did is None:
        raise DeckMissing(f"no deck named {NEW_WORDS_DECK!r}")
    return did


def gate_source_ids(col, gate):
    """Deck IDs whose ord-0 card proves the word is known, for one maturity gate.

    Subdecks included, and every declared source must exist -- see deck_ids_for.
    """
    ids, missing = [], []
    for d in DECKS:
        if gate not in d.gates:
            continue
        found = _subtree_ids(col, d.name)
        ids.extend(found) if found else missing.append(d.name)
    if missing:
        raise DeckMissing(f"{gate} gate source deck(s) missing: "
                          + ", ".join(repr(n) for n in missing))
    if not ids:
        # No source deck declares this gate. `mature` would then be empty and the gate
        # would suspend every released card -- 1,960 of them -- reporting success. An
        # edit to a `gates=` tuple must not be able to do that silently.
        raise DeckMissing(f"no deck declares {gate!r} in its gates; refusing to run")
    return ids


def archive_ids(col):
    """Deck IDs of the archive. RAISES if none is found.

    Two rules, both learned the hard way:

    1. It raises. An empty set read as "nothing is parked", and the maturity gate then
       moved the entire 42,524-card archive into the study decks on its next run — while
       the startup health check reported the collection healthy, because ARCHIVE was
       missing from REQUIRED_DECKS. Every other resolver here raises; this one silently
       did not, and it is the one whose absence causes a destructive write.
    2. The CURRENT name wins outright. A legacy name is consulted only when no deck
       carries the current one, so a new deck someone happens to call `Hidden` is not
       mistaken for the archive. Legacy names exist for reading an old backup, nothing
       more.
    """
    by_name = {d.name: d.id for d in col.decks.all_names_and_ids()}
    for candidate in ARCHIVE_NAMES:
        ids = {i for n, i in by_name.items()
               if n == candidate or n.startswith(candidate + "::")}
        if ids:
            return ids
    raise DeckMissing("no archive deck: none of "
                      + ", ".join(repr(n) for n in ARCHIVE_NAMES) + " exists")


def deck_id_by_name(col, name):
    """NAME BOUNDARY. Resolve a name the user or the model supplied. Raises if missing.

    col.decks.id_for_name() returns None and col.decks.id() CREATES the deck -- one letter
    apart, opposite failure modes, neither raising. Every silent no-op in this codebase
    came from one of those two.
    """
    did = col.decks.id_for_name(name)
    if did is None:
        raise DeckMissing(f"no deck named {name!r}")
    return did


def role_of(col, did):
    """The role of a deck id, or None if it is not one of ours."""
    name = col.decks.name(did)
    if is_archive(name):
        return ARCHIVE
    root = name.split("::", 1)[0]
    d = BY_NAME.get(name) or BY_NAME.get(root)
    return d.role if d else None


def name_of(role):
    """NAME BOUNDARY. The display name for a single-deck role."""
    return _one(role)


def missing_from(col, names=None):
    """Declared deck names absent from the collection."""
    return [n for n in (names or REQUIRED_DECKS) if col.decks.id_for_name(n) is None]


def unexpected_in(col):
    """Deck names present in the collection that this module does not declare.

    A SUBDECK of a declared deck is not unexpected. deck_ids_for and gate_source_ids both
    accept subdecks, so flagging `Mined::x` as a stray while the gate happily counts it
    made two functions disagree and told the model a legitimate deck was a mistake.
    """
    return sorted(d.name for d in col.decks.all_names_and_ids()
                  if d.name not in ALL_NAMES
                  and not any(d.name.startswith(n + "::") for n in ALL_NAMES))


def describe():
    """The list as plain data, for /api/decks and for anything outside this repo."""
    return {
        "decks": [
            {"name": d.name, "role": d.role, "gates": list(d.gates),
             "new_words": d.new_words, "legacy_names": list(d.legacy_names),
             "note": d.note}
            for d in DECKS
        ],
        "roles": {
            "recognition": list(RECOGNITION_DECKS),
            "production": PRODUCTION_DECK,
            "cloze": CLOZE_DECK,
            "archive": ARCHIVE_DECK,
            "archive_names": list(ARCHIVE_NAMES),
            "new_words": NEW_WORDS_DECK,
        },
        "study_decks": list(STUDY_DECKS),
        "allowed_decks": list(ALL_NAMES),
    }
