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
    # consequence: 249 production cards for mined words can never be released.
    Deck("Mined", RECOGNITION, gates=(CLOZE,), new_words=True,
         note="Words added from anywhere that are not in HSK. New arrivals go to the front."),
    Deck("Reverse", PRODUCTION,
         note="Production cards. Filled and suspended by the maturity gate, not by hand."),
    Deck("Cloze", CLOZE, legacy_names=("Vocab Cloze",),
         note="Cloze cards. Filled and suspended by the maturity gate, not by hand."),
    Deck("Archive", ARCHIVE, legacy_names=("Hidden",),
         note="Everything parked. Always suspended. 66,382 notes exist ONLY here."),
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

#: Decks that must exist for the bot to work. `Default` is excluded: Anki guarantees it.
REQUIRED_DECKS = STUDY_DECKS

#: Where a newly created vocabulary note is filed.
NEW_WORDS_DECK = next(d.name for d in DECKS if d.new_words)


def gate_sources(gate):
    """Deck names whose ord-0 card counts as "the user knows this word", for one gate."""
    return tuple(d.name for d in DECKS if gate in d.gates)


def is_archive(name):
    """True for the archive deck under any of its names, or a subdeck of one."""
    return any(name == a or name.startswith(a + "::") or name.startswith(a + "\x1f")
               for a in ARCHIVE_NAMES)


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
