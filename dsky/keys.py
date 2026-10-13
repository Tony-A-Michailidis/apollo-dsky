"""The nineteen DSKY keys and a compact notation for key sequences."""

from __future__ import annotations

from enum import Enum


class Key(str, Enum):
    VERB = "VERB"
    NOUN = "NOUN"
    PLUS = "+"
    MINUS = "-"
    D0 = "0"
    D1 = "1"
    D2 = "2"
    D3 = "3"
    D4 = "4"
    D5 = "5"
    D6 = "6"
    D7 = "7"
    D8 = "8"
    D9 = "9"
    CLR = "CLR"
    PRO = "PRO"
    KEY_REL = "KEY REL"
    ENTR = "ENTR"
    RSET = "RSET"

    @property
    def is_digit(self) -> bool:
        return self.value.isdigit()

    @property
    def digit(self) -> int:
        return int(self.value)


# Checklist shorthand, as written on Apollo cue cards: V37E63E, V16N68E, V05N09E ...
_SHORTHAND = {
    "V": Key.VERB,
    "N": Key.NOUN,
    "E": Key.ENTR,
    "P": Key.PRO,
    "C": Key.CLR,
    "K": Key.KEY_REL,
    "R": Key.RSET,
    "+": Key.PLUS,
    "-": Key.MINUS,
}


def parse_key(text: str) -> Key:
    """Accept a key name ("VERB", "KEY REL", "ENTR"), a single character of shorthand
    ("V", "E", "7", "+") or a lowercase/underscored variant ("key_rel")."""
    t = text.strip().upper().replace("_", " ")
    for k in Key:
        if k.value == t:
            return k
    if len(t) == 1 and t.isdigit():
        return Key(t)
    if t in _SHORTHAND:
        return _SHORTHAND[t]
    raise ValueError(f"unknown DSKY key: {text!r}")


def parse_sequence(text: str) -> list[Key]:
    """Parse cue-card shorthand like "V37E63E" or "V21N01E 01234E" into keys.
    Spaces are ignored."""
    keys: list[Key] = []
    for ch in text.upper():
        if ch.isspace():
            continue
        if ch.isdigit():
            keys.append(Key(ch))
        elif ch in _SHORTHAND:
            keys.append(_SHORTHAND[ch])
        else:
            raise ValueError(f"bad character {ch!r} in key sequence {text!r}")
    return keys
