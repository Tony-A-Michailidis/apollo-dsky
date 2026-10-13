"""Verb table, modelled on Luminary 099. Regular verbs (00-39) work on the display and
the keyboard; extended verbs (40-99) ask the AGC to do something."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Verb:
    number: int
    name: str
    kind: str  # display | monitor | load | control | extended | internal
    comps: tuple[int, ...] = ()  # component indices (0-based) for display/monitor/load
    decimal: bool = False

    def to_dict(self) -> dict:
        return {"number": self.number, "name": self.name, "kind": self.kind}


def _v(n: int, name: str, kind: str, comps=(), decimal=False) -> Verb:
    return Verb(n, name, kind, tuple(comps), decimal)


VERBS: dict[int, Verb] = {
    v.number: v
    for v in [
        _v(1, "Display octal component 1 in R1", "display", (0,)),
        _v(2, "Display octal component 2 in R1", "display", (1,)),
        _v(3, "Display octal component 3 in R1", "display", (2,)),
        _v(4, "Display octal components 1, 2 in R1, R2", "display", (0, 1)),
        _v(5, "Display octal components 1, 2, 3 in R1, R2, R3", "display", (0, 1, 2)),
        _v(6, "Display decimal in R1 or R1, R2 or R1, R2, R3", "display", (0, 1, 2), True),
        _v(7, "Display double precision decimal in R1, R2", "display", (0, 1), True),
        _v(11, "Monitor octal component 1 in R1", "monitor", (0,)),
        _v(12, "Monitor octal component 2 in R1", "monitor", (1,)),
        _v(13, "Monitor octal component 3 in R1", "monitor", (2,)),
        _v(14, "Monitor octal components 1, 2 in R1, R2", "monitor", (0, 1)),
        _v(15, "Monitor octal components 1, 2, 3 in R1, R2, R3", "monitor", (0, 1, 2)),
        _v(16, "Monitor decimal in R1 or R1, R2 or R1, R2, R3", "monitor", (0, 1, 2), True),
        _v(21, "Load component 1 into R1", "load", (0,)),
        _v(22, "Load component 2 into R2", "load", (1,)),
        _v(23, "Load component 3 into R3", "load", (2,)),
        _v(24, "Load components 1, 2 into R1, R2", "load", (0, 1)),
        _v(25, "Load components 1, 2, 3 into R1, R2, R3", "load", (0, 1, 2)),
        _v(32, "Recycle program", "control"),
        _v(33, "Proceed without DSKY inputs", "control"),
        _v(34, "Terminate function", "control"),
        _v(35, "Test lights", "control"),
        _v(36, "Request fresh start", "control"),
        _v(37, "Change program (major mode)", "control"),
        _v(40, "Zero ICDUs", "extended"),
        _v(41, "Coarse align ICDUs", "extended"),
        _v(50, "Please perform", "internal"),
        _v(57, "Permit landing radar updates", "extended"),
        _v(58, "Inhibit landing radar updates", "extended"),
        _v(69, "Cause restart", "extended"),
        _v(96, "Interrupt integration and go to P00", "extended"),
        _v(99, "Please enable engine ignition", "internal"),
    ]
}

LOAD_VERBS = {21, 22, 23, 24, 25}
