"""The DSKY display and lamp state: what the electroluminescent panel is showing."""

from __future__ import annotations

from dataclasses import dataclass, field

BLANK2 = "  "
BLANK5 = "     "

# Left column (white) and right column (amber) of the warning lamp panel, top to bottom.
LEFT_LAMPS = ["UPLINK ACTY", "NO ATT", "STBY", "KEY REL", "OPR ERR"]
RIGHT_LAMPS = ["TEMP", "GIMBAL LOCK", "PROG", "RESTART", "TRACKER", "ALT", "VEL"]
LAMPS = LEFT_LAMPS + RIGHT_LAMPS


@dataclass
class Register:
    """One of R1/R2/R3: a sign lamp (+, - or dark) and five digit positions, each a
    digit character or a space for dark."""

    sign: str = ""
    digits: str = BLANK5

    def blank(self) -> None:
        self.sign = ""
        self.digits = BLANK5

    def to_dict(self) -> dict:
        return {"sign": self.sign, "digits": self.digits}


@dataclass
class Display:
    prog: str = BLANK2
    verb: str = BLANK2
    noun: str = BLANK2
    r1: Register = field(default_factory=Register)
    r2: Register = field(default_factory=Register)
    r3: Register = field(default_factory=Register)
    flash: bool = False  # verb and noun flash together at 1.5 Hz when lit
    comp_acty: bool = False
    lamps: dict[str, bool] = field(default_factory=lambda: {name: False for name in LAMPS})

    @property
    def registers(self) -> tuple[Register, Register, Register]:
        return (self.r1, self.r2, self.r3)

    def blank_registers(self) -> None:
        for r in self.registers:
            r.blank()

    def blank_all(self) -> None:
        self.prog = self.verb = self.noun = BLANK2
        self.flash = False
        self.blank_registers()

    def lamp(self, name: str, on: bool) -> None:
        if name not in self.lamps:
            raise KeyError(name)
        self.lamps[name] = on

    def to_dict(self) -> dict:
        return {
            "prog": self.prog,
            "verb": self.verb,
            "noun": self.noun,
            "r1": self.r1.to_dict(),
            "r2": self.r2.to_dict(),
            "r3": self.r3.to_dict(),
            "flash": self.flash,
            "comp_acty": self.comp_acty,
            "lamps": dict(self.lamps),
        }
