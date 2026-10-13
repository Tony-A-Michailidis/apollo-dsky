"""The keyboard half of the DSKY: what each key does given what has been keyed so far.

The AGC routine that did this was called PINBALL GAME BUTTONS AND LIGHTS. The rules
implemented here are the ones the crew lived with:

* VERB then two digits, NOUN then two digits, ENTR executes.
* ENTR with only a new verb keyed uses the noun already on the display, and vice versa.
* ENTR with nothing keyed re-executes the verb/noun on the display.
* A load (V21-V25) flashes and blanks the register to be loaded. Decimal data needs a
  sign first and five digits; octal data takes five digits 0-7 and no sign.
* CLR blanks the register being loaded; CLR on an already blank register backs up one.
* KEY REL gives the display back to the running program.
* RSET turns the alarm lamps off. Anything nonsensical lights OPR ERR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from .display import BLANK2
from .keys import Key
from .nouns import Noun, decode

if TYPE_CHECKING:  # pragma: no cover
    from .agc import AGC


class OprErr(Exception):
    """Operator error: the keystroke made no sense in the current state."""


@dataclass
class Load:
    noun: Noun
    comps: tuple[int, ...]  # component indices, loaded in this order
    regs: tuple[int, ...]  # display register (0-2) for each component
    on_complete: Callable[[list[float]], None]
    index: int = 0
    values: list[float] = field(default_factory=list)

    @property
    def comp(self):
        return self.noun.components[self.comps[self.index]]

    @property
    def reg_index(self) -> int:
        return self.regs[self.index]


class Pinball:
    def __init__(self, agc: "AGC") -> None:
        self.agc = agc
        self.entry: str | None = None  # None | verb | noun | data | program | address
        self.verb_buf = ""
        self.noun_buf = ""
        self.verb_keyed = False
        self.noun_keyed = False
        self.load: Load | None = None
        self.sign = ""
        self.buf = ""

    # ------------------------------------------------------------------ helpers

    @property
    def disp(self):
        return self.agc.display

    @property
    def keyboard_busy(self) -> bool:
        """True while the operator is in the middle of keying something."""
        return self.entry is not None

    def reset(self) -> None:
        self.entry = None
        self.verb_buf = self.noun_buf = ""
        self.verb_keyed = self.noun_keyed = False
        self.load = None
        self.sign = self.buf = ""

    def to_dict(self) -> dict:
        return {
            "entry": self.entry,
            "verb_buf": self.verb_buf,
            "noun_buf": self.noun_buf,
            "data": (self.sign + self.buf) if self.entry in ("data", "address") else "",
            "load_register": (self.load.reg_index + 1) if self.load and self.entry == "data" else None,
        }

    # ------------------------------------------------------------------ entry points used by the AGC

    def begin_load(self, noun: Noun, comps, regs, on_complete) -> None:
        self.reset()
        self.load = Load(noun, tuple(comps), tuple(regs), on_complete)
        self.entry = "data"
        self.disp.registers[self.load.reg_index].blank()

    def begin_program_entry(self) -> None:
        self.reset()
        self.entry = "program"
        self.disp.noun = BLANK2

    def begin_address(self) -> None:
        self.reset()
        self.entry = "address"
        self.disp.r3.blank()

    # ------------------------------------------------------------------ keys

    def press(self, key: Key) -> None:
        try:
            self._press(key)
        except OprErr as e:
            self.disp.lamp("OPR ERR", True)
            self.agc.log(f"OPR ERR on {key.value}: {e}")

    def _press(self, key: Key) -> None:
        if self.agc.standby and key is not Key.PRO:
            return  # in standby only PRO does anything
        if key is Key.VERB:
            self._verb()
        elif key is Key.NOUN:
            self._noun()
        elif key.is_digit:
            self._digit(key.digit)
        elif key in (Key.PLUS, Key.MINUS):
            self._sign(key.value)
        elif key is Key.ENTR:
            self._entr()
        elif key is Key.CLR:
            self._clr()
        elif key is Key.KEY_REL:
            self.reset()
            self.agc.key_release()
        elif key is Key.RSET:
            self.agc.reset_lamps()
        elif key is Key.PRO:
            self.reset()
            self.agc.proceed()

    def _verb(self) -> None:
        if self.entry in ("data", "address", "program"):
            self.load = None
            self.sign = self.buf = ""
        self.entry = "verb"
        self.verb_buf = ""
        self.verb_keyed = True
        self.noun_keyed = False
        self.disp.verb = BLANK2

    def _noun(self) -> None:
        if self.entry in ("data", "address", "program"):
            self.load = None
            self.sign = self.buf = ""
        self.entry = "noun"
        self.noun_buf = ""
        self.noun_keyed = True
        self.disp.noun = BLANK2

    def _digit(self, d: int) -> None:
        e = self.entry
        if e == "verb":
            if len(self.verb_buf) >= 2:
                raise OprErr("verb already has two digits")
            self.verb_buf += str(d)
            self.disp.verb = self.verb_buf.ljust(2)
        elif e in ("noun", "program"):
            if len(self.noun_buf) >= 2:
                raise OprErr("noun already has two digits")
            self.noun_buf += str(d)
            self.disp.noun = self.noun_buf.ljust(2)
        elif e == "address":
            if d > 7:
                raise OprErr("addresses are octal")
            if len(self.buf) >= 5:
                raise OprErr("address already has five digits")
            self.buf += str(d)
            self.disp.r3.digits = self.buf.ljust(5)
        elif e == "data":
            assert self.load is not None
            if not self.load.comp.decimal and d > 7:
                raise OprErr("octal load, digits 0-7 only")
            if len(self.buf) >= 5:
                raise OprErr("register already has five digits")
            self.buf += str(d)
            self.disp.registers[self.load.reg_index].digits = self.buf.ljust(5)
        else:
            raise OprErr("no verb, noun or load in progress")

    def _sign(self, s: str) -> None:
        if self.entry != "data" or self.load is None:
            raise OprErr("sign keyed outside a data load")
        if self.buf:
            raise OprErr("sign must be keyed before the digits")
        if not self.load.comp.decimal:
            raise OprErr("octal load takes no sign")
        self.sign = s
        self.disp.registers[self.load.reg_index].sign = s

    def _entr(self) -> None:
        e = self.entry
        if e in ("verb", "noun"):
            if self.verb_keyed:
                if len(self.verb_buf) != 2:
                    raise OprErr("verb needs two digits")
                verb = int(self.verb_buf)
            else:
                if not self.disp.verb.strip():
                    raise OprErr("no verb on the display")
                verb = int(self.disp.verb)
            if self.noun_keyed:
                if len(self.noun_buf) != 2:
                    raise OprErr("noun needs two digits")
                noun: int | None = int(self.noun_buf)
            else:
                noun = int(self.disp.noun) if self.disp.noun.strip() else None
            self.reset()
            self.agc.execute(verb, noun)
        elif e == "program":
            if len(self.noun_buf) != 2:
                raise OprErr("program needs two digits")
            n = int(self.noun_buf)
            self.reset()
            self.agc.select_program(n)
        elif e == "address":
            if len(self.buf) != 5:
                raise OprErr("address needs five octal digits")
            addr = int(self.buf, 8)
            self.reset()
            self.agc.specify_address(addr)
        elif e == "data":
            assert self.load is not None
            comp = self.load.comp
            if comp.decimal and not self.sign:
                raise OprErr("decimal load needs a + or - first")
            if len(self.buf) != 5:
                raise OprErr("five digits required")
            value = decode(comp.fmt, self.sign, self.buf)
            self.load.values.append(value)
            self.load.index += 1
            self.sign = self.buf = ""
            if self.load.index < len(self.load.comps):
                self.disp.registers[self.load.reg_index].blank()
            else:
                load = self.load
                self.reset()
                load.on_complete(load.values)
        else:
            if not self.disp.verb.strip():
                raise OprErr("nothing keyed and no verb on the display")
            noun = int(self.disp.noun) if self.disp.noun.strip() else None
            self.agc.execute(int(self.disp.verb), noun)

    def _clr(self) -> None:
        e = self.entry
        if e == "data" and self.load is not None:
            if self.buf or self.sign:
                self.sign = self.buf = ""
                self.disp.registers[self.load.reg_index].blank()
            elif self.load.index > 0:
                self.load.index -= 1
                self.load.values.pop()
                self.disp.registers[self.load.reg_index].blank()
        elif e == "verb":
            self.verb_buf = ""
            self.disp.verb = BLANK2
        elif e in ("noun", "program"):
            self.noun_buf = ""
            self.disp.noun = BLANK2
        elif e == "address":
            self.buf = ""
            self.disp.r3.blank()
