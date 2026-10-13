"""A simulated Luminary-style AGC behind the DSKY.

It owns the display, runs the programs (P00, P06, P52, P63-P66, P68, P70/71), executes
verbs, keeps the alarm registers, and drives the descent model. The display ownership
rules follow the real machine: a program request that arrives while the operator is
mid-keystroke lights KEY REL and waits; a completed operator display (say V16N68) stays
up until the program asks for something new or the operator presses KEY REL.
"""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass
from typing import Callable

from .descent import FT_PER_NMI, LM, MAX_VAR_THROTTLE, quadratic_guidance
from .display import BLANK2, Display
from .keys import Key, parse_sequence
from .nouns import NOUNS, Component, _FORMATS, encode
from .pinball import OprErr, Pinball
from .verbs import LOAD_VERBS, VERBS

GET_START = 102 * 3600 + 30 * 60  # 102:30:00 GET; Apollo 11 PDI was at 102:33:05
TIG_LEAD = 90.0  # seconds from selecting P63 to ignition
HI_GATE_ALT = 7_500.0
BRAKING_TGO = 482.0  # seconds of guided braking after throttle-up
APPROACH_TTG = 150.0
LAMP_TEST_SECONDS = 5.0
RESET_LAMPS = ("OPR ERR", "PROG", "RESTART", "TRACKER", "GIMBAL LOCK", "ALT", "VEL", "TEMP", "NO ATT")

ALARMS: dict[int, str] = {
    0o1201: "Executive overflow: no VAC areas available",
    0o1202: "Executive overflow: no core sets available",
    0o1210: "Two programs using the same device",
    0o1520: "V37 request not permitted at this time",
    0o500: "Landing radar antenna not in position",
}

PROGRAMS: dict[int, str] = {
    0: "LGC idle",
    6: "PGNS power down (standby)",
    52: "IMU realign",
    63: "Braking phase",
    64: "Approach phase",
    65: "Landing phase (automatic)",
    66: "Landing phase (rate of descent)",
    68: "Landing confirmation",
    70: "DPS abort",
    71: "APS abort",
}
SELECTABLE = {0, 6, 52, 63, 68, 70, 71}

# A few erasable addresses from Luminary, for V01N01 pokes.
ERASABLE_NAMES = {0o24: "TIME2", 0o25: "TIME1", 0o375: "FAILREG", 0o376: "FAILREG+1", 0o377: "FAILREG+2"}


def fmt_get(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 3600:03d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


@dataclass
class Request:
    """Something that wants the display: a program or the operator."""

    verb: int
    noun: int | None
    flash: bool = False
    kind: str = "display"  # display | load | proceed | program | address
    comps: tuple[int, ...] = ()
    regs: tuple[int, ...] = ()
    decimal: bool = True
    monitor: bool = True
    source: str = "program"
    values: dict[int, object] | None = None  # component overrides (checklist codes, options)
    on_pro: Callable[[], None] | None = None
    on_entr: Callable[[list[float]], None] | None = None
    on_terminate: Callable[[], None] | None = None
    on_recycle: Callable[[], None] | None = None
    seq: int = 0

    @property
    def waiting_for(self) -> str | None:
        if self.kind == "load":
            return "data"
        if self.flash and self.on_pro:
            return "PRO"
        return None

    def to_dict(self) -> dict:
        return {
            "verb": self.verb,
            "noun": self.noun,
            "flash": self.flash,
            "kind": self.kind,
            "source": self.source,
            "waiting_for": self.waiting_for,
        }


class AGC:
    def __init__(self, seed: int = 11, get_start: float = GET_START, tig_lead: float = TIG_LEAD) -> None:
        self.display = Display()
        self.pinball = Pinball(self)
        self.rng = random.Random(seed)
        self.clock = float(get_start)
        self.tig_lead = tig_lead
        self.events: deque[dict] = deque(maxlen=400)
        self.lm = LM()
        self.program = 0
        self.failreg = [0, 0, 0]
        self.cells: dict[str, object] = {}
        self.erasable: dict[int, int] = {}
        self.address = 0
        self.tig: float | None = None
        self.tevent: float | None = None
        self.rr_switch = "LGC"  # LGC | SLEW | AUTO ; anything but LGC loads the executive
        self.standby = False
        self.lamp_test_until: float | None = None
        self._saved_lamps: dict[str, bool] | None = None
        self.blank_until: float | None = None
        self.busy_until = 0.0
        self.uplink_until = 0.0
        self.prog_request: Request | None = None  # what the running program wants shown
        self.op_request: Request | None = None  # what the operator asked for
        self.painted: Request | None = None  # what is actually on the panel
        self.deferred = False  # a program request is waiting behind KEY REL
        self._seq = 0
        self.pstate: dict = {}
        self.armed = False
        self.vh_cmd = 0.0
        self.tgo = 508.0
        self.ttg = APPROACH_TTG
        self.overflow_timer = 30.0
        self.guidance_timer = 0.0
        self.display.prog = "00"
        self._static_cells()
        self._update_cells()
        self.log("Fresh start. P00 running.")

    # ------------------------------------------------------------------ logging / keys

    def log(self, text: str, level: str = "info") -> None:
        self.events.append({"t": self.clock, "get": fmt_get(self.clock), "text": text, "level": level})

    def press(self, key: Key) -> None:
        self.pinball.press(key)
        self._refresh()

    def press_sequence(self, text: str) -> None:
        for key in parse_sequence(text):
            self.press(key)

    def uplink(self, text: str) -> None:
        """Keystrokes injected over the digital uplink, as the ground could do."""
        self.display.lamp("UPLINK ACTY", True)
        self.uplink_until = self.clock + 2.0
        self.log(f"UPLINK: {text}")
        self.press_sequence(text)

    # ------------------------------------------------------------------ display ownership

    def _request(self, verb: int, noun: int | None, **kw) -> Request:
        self._seq += 1
        req = Request(verb, noun, seq=self._seq, **kw)
        self.prog_request = req
        if self.pinball.keyboard_busy:
            self.deferred = True
            self.display.lamp("KEY REL", True)
        else:
            self.deferred = False
            self.display.lamp("KEY REL", False)
            self.op_request = None
            self.painted = req
            self._show(req)
        return req

    def _operator_show(self, req: Request) -> None:
        self.op_request = req
        self.painted = req
        self._show(req)

    def _clear_program_request(self) -> None:
        old = self.prog_request
        self.prog_request = None
        self.deferred = False
        self.display.lamp("KEY REL", False)
        if self.painted is old:
            self.painted = None
            self._blank_vn()

    def _blank_vn(self) -> None:
        d = self.display
        d.verb = d.noun = BLANK2
        d.flash = False
        d.blank_registers()

    def _reshow(self) -> None:
        """Give the display to the program (KEY REL, restart, end of an operator entry)."""
        self.op_request = None
        self.deferred = False
        self.display.lamp("KEY REL", False)
        self.painted = self.prog_request
        if self.painted is not None:
            self._show(self.painted)
        else:
            self._blank_vn()

    def _repaint(self) -> None:
        """Redraw whatever was on the panel (after a lamp test or a blank)."""
        if self.painted is not None:
            self._show(self.painted)
        else:
            self._blank_vn()

    def _show(self, req: Request) -> None:
        d = self.display
        d.verb = f"{req.verb:02d}"
        d.noun = f"{req.noun:02d}" if req.noun is not None else BLANK2
        d.flash = req.flash
        if req.kind == "program":
            self.pinball.begin_program_entry()
            return
        if req.kind == "address":
            d.blank_registers()
            self.pinball.begin_address()
            return
        self._paint_registers(req, full=True)
        if req.kind == "load":
            noun = NOUNS[req.noun]  # type: ignore[index]
            self.pinball.begin_load(noun, req.comps, req.regs, lambda vals, r=req: self._load_done(r, vals))

    def _paint_registers(self, req: Request, full: bool) -> None:
        d = self.display
        noun = NOUNS.get(req.noun) if req.noun is not None else None
        if noun is None:
            if full:
                d.blank_registers()
            return
        if req.kind == "address" or (req.kind == "load" and self.pinball.entry == "data"):
            if full:
                d.blank_registers()
            return
        if full:
            d.blank_registers()
        for comp_i, reg_i in zip(req.comps, req.regs):
            comp = noun.components[comp_i]
            value = req.values[comp_i] if req.values and comp_i in req.values else self._cell(comp.key)
            sign, digits = self._encode(comp, value, req.decimal)
            reg = d.registers[reg_i]
            reg.sign, reg.digits = sign, digits

    @staticmethod
    def _encode(comp: Component, value, decimal: bool) -> tuple[str, str]:
        if decimal or comp.fmt == "octal":
            return encode(comp.fmt, value)
        # Octal display of a decimal quantity shows its scaled binary, as the real AGC did.
        if isinstance(value, tuple):
            n = int(value[0]) * 100 + int(value[1])
        else:
            n = int(round(float(value) * _FORMATS[comp.fmt][0]))
        return encode("octal", n)

    def _refresh(self) -> None:
        d = self.display
        if self.lamp_test_until is not None or self.standby:
            return
        if self.blank_until is not None:
            if self.clock < self.blank_until:
                d.verb = d.noun = BLANK2
                d.flash = False
                d.blank_registers()
                return
            self.blank_until = None
            self._repaint()
        painted = self.painted
        if painted is not None and painted.monitor:
            self._paint_registers(painted, full=False)

    # ------------------------------------------------------------------ cells (erasable memory by name)

    def _static_cells(self) -> None:
        self.cells.update(
            {
                "ang_err": 0.0,
                "opt_code": 1,
                "opt_data": 1,
                "checklist": 0,
                "fdai.r": 0.0,
                "fdai.p": 0.0,
                "fdai.y": 0.0,
                "cdu.x": 0.0,
                "cdu.y": 0.0,
                "cdu.z": 0.0,
                "vg": 0.0,
                "zero": 0.0,
                "apo": 60.2,
                "peri": 8.3,
                "tff": 0.0,
                "lr_pos": 1,
                "asc_vh": 5535.0,
                "asc_vr": 32.0,
                "dgyro.x": 0.012,
                "dgyro.y": -0.034,
                "dgyro.z": 0.008,
                "lsc.z": 0.0,
                "lsc.y": 0.0,
                "lsc.x": 0.0,
            }
        )

    def _update_cells(self) -> None:
        lm, c = self.lm, self.cells
        c["h"] = lm.computed_h
        c["hdot"] = lm.vh
        c["vfwd"] = -lm.vx
        c["vabs"] = lm.vabs
        c["dalt"] = lm.dalt
        c["tgo"] = self.tgo
        c["tfi"] = (self.clock - self.tig) if self.tig is not None else 0.0
        c["crossrange"] = 0.4 * min(1.0, lm.x / 1_580_000.0)
        c["range_site"] = lm.range_site_nmi
        c["ttg_lpd"] = (self.ttg if self.program == 64 else 0, lm.lpd_angle)
        c["throttle_pct"] = lm.throttle * 100.0
        c["dv_acc"] = lm.dv_acc
        c["lat"] = lm.lat
        c["lon"] = lm.lon
        c["alt_nmi"] = lm.computed_h / FT_PER_NMI
        c["lr_range"] = lm.h / math.cos(math.radians(24)) if lm.lr_locked else 0.0
        c["lr_vx"] = -lm.vx if lm.lr_locked else 0.0
        c["lr_vy"] = 0.0
        c["lr_vz"] = lm.vh if lm.lr_locked else 0.0
        c["vg"] = max(0.0, lm.vabs - 50.0) if self.program in (63, 64) else 0.0
        c["fdai.p"] = lm.pitch

    def _time_cell(self, base: str) -> float:
        if base == "clock":
            return self.clock
        if base == "tig":
            return self.tig if self.tig is not None else 0.0
        if base == "tevent":
            return self.tevent if self.tevent is not None else 0.0
        if base == "tfe":
            return (self.tevent - self.clock) if self.tevent is not None else 0.0
        return 0.0

    def _cell(self, key: str):
        if key[-2:] in (".h", ".m", ".s") and key[:-2] in ("clock", "tig", "tevent", "tfe"):
            t = self._time_cell(key[:-2])
            sign = -1 if t < 0 else 1
            t = abs(t)
            h, rem = divmod(t, 3600)
            m, s = divmod(rem, 60)
            part = {"h": int(h), "m": int(m), "s": s}[key[-1]]
            return sign * part
        if key.startswith("failreg."):
            return self.failreg[int(key[-1])]
        if key.startswith("mem."):
            return self.read_erasable(self.address + int(key[-1]))
        return self.cells.get(key, 0.0)

    def _set_cell(self, key: str, value: float) -> None:
        if key[-2:] in (".h", ".m", ".s") and key[:-2] in ("tig", "tevent"):
            base = key[:-2]
            t = self._time_cell(base)
            h, rem = divmod(abs(t), 3600)
            m, s = divmod(rem, 60)
            parts = {"h": int(h), "m": int(m), "s": s}
            parts[key[-1]] = abs(value)
            total = parts["h"] * 3600 + parts["m"] * 60 + parts["s"]
            setattr(self, base, total)
            if base == "tig":
                self.log(f"TIG loaded: {fmt_get(total)}")
            return
        if key.startswith("mem."):
            self.erasable[self.address + int(key[-1])] = int(value) & 0o77777
            return
        if key.startswith("lsc."):
            if key == "lsc.z":
                self.lm.site_shift += value
                self.log(f"Landing site redesignated {value:+.0f} ft downrange (N69)")
            self.cells[key] = value
            return
        self.cells[key] = value

    def read_erasable(self, addr: int) -> int:
        addr &= 0o7777
        if addr == 0o24:
            return (int(self.clock * 100) >> 14) & 0o37777
        if addr == 0o25:
            return int(self.clock * 100) & 0o37777
        if 0o375 <= addr <= 0o377:
            return self.failreg[addr - 0o375]
        return self.erasable.get(addr, 0)

    # ------------------------------------------------------------------ verbs

    def execute(self, verb: int, noun: int | None) -> None:
        v = VERBS.get(verb)
        if v is None:
            raise OprErr(f"V{verb:02d} is not defined")
        if v.kind in ("display", "monitor", "load"):
            if noun is None:
                raise OprErr("no noun")
            n = NOUNS.get(noun)
            if n is None:
                raise OprErr(f"N{noun:02d} is not defined")
            comps = tuple(i for i in v.comps if i < len(n.components))
            if not comps:
                raise OprErr(f"N{noun:02d} has no component {v.comps[0] + 1}")
            regs = comps if (v.kind == "load" or len(comps) > 1) else (0,)
            if v.decimal and any(n.components[i].fmt == "octal" for i in comps):
                raise OprErr(f"N{noun:02d} is octal only")
            if n.special == "address":
                req = Request(verb, noun, flash=True, kind="address", comps=comps, regs=regs,
                              decimal=(v.decimal or v.kind == "load"), monitor=(v.kind == "monitor"),
                              source="operator")
                self._operator_show(req)
                return
            req = Request(verb, noun, flash=(v.kind == "load"), kind=("load" if v.kind == "load" else "display"),
                          comps=comps, regs=regs, decimal=(v.decimal or v.kind == "load"),
                          monitor=(v.kind == "monitor"), source="operator")
            self._operator_show(req)
            return
        if v.kind == "control":
            self._control_verb(verb)
            return
        if v.kind == "extended":
            self._extended_verb(verb, noun)
            return
        raise OprErr(f"V{verb:02d} is for internal use only")

    def _control_verb(self, verb: int) -> None:
        req = self.prog_request
        if verb == 32:
            if req and req.on_recycle:
                req.on_recycle()
            else:
                raise OprErr("nothing to recycle")
        elif verb == 33:
            self.proceed()
        elif verb == 34:
            if req and req.on_terminate:
                self.log("V34: terminate")
                req.on_terminate()
            else:
                raise OprErr("nothing to terminate")
        elif verb == 35:
            self._lamp_test()
        elif verb == 36:
            self.fresh_start()
        elif verb == 37:
            self._operator_show(Request(37, None, flash=True, kind="program", monitor=False, source="operator"))

    def _extended_verb(self, verb: int, noun: int | None) -> None:
        if verb in (40, 41):
            if noun != 20:
                raise OprErr(f"V{verb} needs N20")
            self.log("ICDUs zeroed" if verb == 40 else "ICDUs coarse aligned")
            self.busy_until = self.clock + 2.0
            self._reshow()
        elif verb == 57:
            self.lm.lr_permit = True
            self.log("V57: landing radar updates permitted")
            self._reshow()
        elif verb == 58:
            self.lm.lr_permit = False
            self.log("V58: landing radar updates inhibited")
            self._reshow()
        elif verb == 69:
            self.display.lamp("RESTART", True)
            self._restart("V69 commanded restart")
        elif verb == 96:
            self.log("V96: integration interrupted")
            self._enter_program(0)

    # ------------------------------------------------------------------ responses: PRO, KEY REL, RSET, loads

    def proceed(self) -> None:
        if self.standby:
            self.standby = False
            self.display.lamp("STBY", False)
            self.display.prog = f"{self.program:02d}"
            self.log("Out of standby")
            self._reshow()
            return
        op = self.op_request
        if op is not None and op.kind in ("program", "address", "load"):
            self.log("PRO: operator entry abandoned")
            self._reshow()
            return
        req = self.prog_request
        if req is not None and req.flash and req.on_pro is not None:
            cb = req.on_pro
            self.log(f"PRO on V{req.verb:02d}N{req.noun:02d}" if req.noun is not None else f"PRO on V{req.verb:02d}")
            cb()
        else:
            self.log("PRO: nothing waiting")

    def key_release(self) -> None:
        self._reshow()

    def reset_lamps(self) -> None:
        for name in RESET_LAMPS:
            self.display.lamp(name, False)
        self.log("RSET")

    def _load_done(self, req: Request, values: list[float]) -> None:
        req.flash = False
        req.kind = "display"
        self.display.flash = False
        if req.source == "operator":
            noun = NOUNS[req.noun]  # type: ignore[index]
            for comp_i, val in zip(req.comps, values):
                self._set_cell(noun.components[comp_i].key, val)
            self.log(f"V{req.verb:02d}N{req.noun:02d} loaded: {values}")
            self._paint_registers(req, full=False)
        elif req.on_entr is not None:
            req.on_entr(values)

    def specify_address(self, addr: int) -> None:
        req = self.op_request
        if req is None or req.kind != "address":
            raise OprErr("no address requested")
        self.address = addr
        req.flash = False
        self.display.flash = False
        name = ERASABLE_NAMES.get(addr, "")
        self.log(f"N01 address {addr:05o}{' (' + name + ')' if name else ''}")
        if req.verb in LOAD_VERBS:
            req.kind = "load"
            req.flash = True
            self._show(req)
        else:
            req.kind = "display"
            self._paint_registers(req, full=True)

    # ------------------------------------------------------------------ alarms, restarts, lamp test, fresh start

    def alarm(self, code: int) -> None:
        if self.failreg[0] == 0:
            self.failreg[0] = code
        elif self.failreg[1] == 0:
            self.failreg[1] = code
        self.failreg[2] = code
        self.display.lamp("PROG", True)
        self.log(f"PROGRAM ALARM {code:05o}: {ALARMS.get(code, 'unknown')}", level="alarm")

    def _restart(self, reason: str) -> None:
        self.log(f"Software restart ({reason}); display re-established", level="alarm")
        self.busy_until = self.clock + 1.5
        self.pinball.reset()
        self._reshow()

    def _lamp_test(self) -> None:
        d = self.display
        self._saved_lamps = dict(d.lamps)
        for name in d.lamps:
            d.lamps[name] = True
        d.comp_acty = True
        d.prog = d.verb = d.noun = "88"
        d.flash = False
        for r in d.registers:
            r.sign, r.digits = "±", "88888"
        self.lamp_test_until = self.clock + LAMP_TEST_SECONDS
        self.log("V35 lamp test")

    def _end_lamp_test(self) -> None:
        d = self.display
        if self._saved_lamps:
            d.lamps.update(self._saved_lamps)
        self._saved_lamps = None
        self.lamp_test_until = None
        d.prog = f"{self.program:02d}"
        self._repaint()

    def fresh_start(self) -> None:
        d = self.display
        self.program = 0
        self.failreg = [0, 0, 0]
        for name in d.lamps:
            d.lamps[name] = False
        self.standby = False
        self.lamp_test_until = None
        self.blank_until = None
        self.prog_request = self.op_request = self.painted = None
        self.deferred = False
        self.pinball.reset()
        self.pstate = {}
        if self.lm.engine_on:
            self.lm.engine_on = False
            self.log("Fresh start with the engine running: DPS shut down", level="alarm")
        d.blank_all()
        d.prog = "00"
        self.log("V36 fresh start. P00 running.")

    # ------------------------------------------------------------------ programs

    def select_program(self, n: int) -> None:
        if n not in PROGRAMS:
            self._reshow()
            raise OprErr(f"P{n:02d} is not in this rope")
        lm = self.lm
        not_now = (
            n not in SELECTABLE
            or (lm.engine_on and n not in (0, 70, 71))
            or (n == 68 and not lm.landed)
            or (n == 63 and (lm.landed or lm.engine_on))
            or (n in (70, 71) and self.program not in (63, 64, 65, 66))
        )
        if not_now:
            self.alarm(0o1520)
            self._reshow()
            return
        self._enter_program(n)

    def _enter_program(self, n: int) -> None:
        self.program = n
        self.display.prog = f"{n:02d}"
        self.op_request = self.prog_request = self.painted = None
        self.deferred = False
        self.display.lamp("KEY REL", False)
        self.pinball.reset()
        self.pstate = {}
        self.log(f"P{n:02d} {PROGRAMS[n]}")
        {
            0: self._p00,
            6: self._p06,
            52: self._p52,
            63: self._p63,
            64: self._p64,
            65: self._p65,
            66: self._p66,
            68: self._p68,
            70: self._p70,
            71: self._p70,
        }[n]()

    def _to_p00(self) -> None:
        self._enter_program(0)

    # P00
    def _p00(self) -> None:
        if self.lm.engine_on:
            self.lm.engine_on = False
            self.log("DPS shut down (P00 selected with the engine running)", level="alarm")
        self._blank_vn()

    # P06 standby
    def _p06(self) -> None:
        self._request(50, 25, flash=True, kind="proceed", comps=(0,), regs=(0,), decimal=False,
                      values={0: 0o62}, on_pro=self._p06_pro, on_terminate=self._to_p00)

    def _p06_pro(self) -> None:
        self.standby = True
        self.display.blank_all()
        self.display.lamp("STBY", True)
        self.log("PGNS in standby. PRO to resume.")

    # P52 IMU realign (abbreviated)
    def _p52(self) -> None:
        self._request(4, 6, flash=True, kind="proceed", comps=(0, 1), regs=(0, 1), decimal=False,
                      values={0: 1, 1: 1}, on_pro=self._p52_compute, on_terminate=self._to_p00)

    def _p52_compute(self) -> None:
        self.pstate = {"stage": "compute", "until": self.clock + 3.0}
        self.busy_until = self.clock + 3.0
        self._clear_program_request()
        self.log("P52: computing gyro torquing angles")

    def _p52_torque(self) -> None:
        self.pstate = {"stage": "torque", "until": self.clock + 2.0}
        self.busy_until = self.clock + 2.0
        self._clear_program_request()
        self.log("P52: torquing gyros")

    # P63 braking
    def _p63(self) -> None:
        self.tig = self.clock + self.tig_lead
        self.armed = False
        self.tgo = 508.0
        # Selecting P63 means we are coasting towards PDI: put the LM where it must be
        # now so that it reaches the PDI point (260 nmi out, 50,000 ft) at TIG.
        lm = self.lm
        if not lm.engine_on and not lm.landed and lm.t_burn == 0.0:
            lm.x = 1_580_000.0 - lm.vx * self.tig_lead
            lm.h = 50_000.0
        self.lm.history.clear()
        self.pstate = {"stage": "n61"}
        self.log(f"P63: TIG {fmt_get(self.tig)}; FL V06N61")
        self._request(6, 61, flash=True, kind="proceed", comps=(0, 1, 2), regs=(0, 1, 2),
                      on_pro=self._p63_pro1, on_terminate=self._to_p00, on_recycle=self._p63)

    def _p63_pro1(self) -> None:
        self.pstate["stage"] = "coast"
        self._request(6, 61, comps=(0, 1, 2), regs=(0, 1, 2))

    def _p63_arm(self) -> None:
        self.armed = True
        self.pstate["stage"] = "armed"
        self.log("Engine ignition enabled")
        self._request(6, 62, comps=(0, 1, 2), regs=(0, 1, 2))

    def _ignite(self) -> None:
        lm = self.lm
        lm.engine_on = True
        self._braking_guidance(fixed=0.10)
        self.pstate["stage"] = "burn"
        self.log("DPS ignition, 10% thrust", level="alarm")

    def _braking_guidance(self, fixed: float | None = None) -> None:
        lm = self.lm
        T = max(self.tgo, 8.0)
        ax = quadratic_guidance(lm.x, lm.vx, 26_000.0 + lm.site_shift, -500.0, T)
        ah = quadratic_guidance(lm.h, lm.vh, HI_GATE_ALT, -150.0, T)
        lm.command_accel(ax, ah, fixed_throttle=fixed)

    def _approach_guidance(self) -> None:
        lm = self.lm
        T = max(self.ttg, 8.0)
        ax = quadratic_guidance(lm.x, lm.vx, lm.site_shift, 0.0, T)
        ah = quadratic_guidance(lm.h, lm.vh, 100.0, -3.0, T)
        lm.command_accel(ax, ah)
        lm.throttle = min(lm.throttle, MAX_VAR_THROTTLE)

    # P64 approach
    def _p64(self) -> None:
        self.ttg = APPROACH_TTG
        self.cells["lr_pos"] = 2
        self._request(6, 64, comps=(0, 1, 2), regs=(0, 1, 2))

    # P65 automatic landing
    def _p65(self) -> None:
        self.vh_cmd = -3.0
        self._request(6, 60, comps=(0, 1, 2), regs=(0, 1, 2))

    # P66 rate of descent
    def _p66(self) -> None:
        self.vh_cmd = float(round(self.lm.vh))
        self._request(6, 60, comps=(0, 1, 2), regs=(0, 1, 2))

    # P68 landing confirmation
    def _p68(self) -> None:
        self._request(6, 43, flash=True, kind="proceed", comps=(0, 1, 2), regs=(0, 1, 2),
                      on_pro=self._to_p00, on_terminate=self._to_p00)

    # P70 / P71 abort
    def _p70(self) -> None:
        lm = self.lm
        lm.engine_on = True
        lm.lr_permit = False
        self.pstate = {"stage": "abort"}
        self._request(6, 63, comps=(0, 1, 2), regs=(0, 1, 2))
        self.log("ABORT: climbing to orbit", level="alarm")

    # ------------------------------------------------------------------ crew switches that are not DSKY keys

    def set_rr_switch(self, position: str) -> None:
        position = position.upper()
        if position not in ("LGC", "SLEW", "AUTO"):
            raise ValueError("rendezvous radar switch: LGC, SLEW or AUTO")
        if position != self.rr_switch:
            self.rr_switch = position
            self.log(f"Rendezvous radar mode switch to {position}")

    def rod_click(self, delta: int) -> None:
        """One click of the rate-of-descent switch: +-1 ft/s. In P64/P65 the first click
        (with attitude hold) takes the LM into P66."""
        if self.program in (64, 65):
            self._enter_program(66)
        if self.program != 66:
            return
        self.vh_cmd += float(delta)
        self.log(f"ROD {'+' if delta > 0 else '-'}1: commanded rate {self.vh_cmd:+.0f} ft/s")

    def redesignate(self, clicks: int) -> None:
        """LPD redesignation in P64: each click moves the site ~0.5 deg in pitch."""
        if self.program != 64:
            return
        shift = clicks * self.lm.h * math.tan(math.radians(0.5))
        self.lm.site_shift += shift
        self.log(f"LPD redesignation {clicks:+d}: site moved {shift:+.0f} ft downrange")

    def engine_stop(self) -> None:
        if self.lm.engine_on:
            self.lm.engine_on = False
            self.lm.throttle = 0.0
            self.log("ENGINE STOP", level="alarm")

    def abort(self, stage: bool = False) -> None:
        if self.program in (63, 64, 65, 66):
            self._enter_program(71 if stage else 70)

    # ------------------------------------------------------------------ time

    def tick(self, dt: float) -> None:
        self.clock += dt
        d = self.display
        if self.uplink_until and self.clock >= self.uplink_until:
            d.lamp("UPLINK ACTY", False)
            self.uplink_until = 0.0
        if self.lamp_test_until is not None:
            if self.clock >= self.lamp_test_until:
                self._end_lamp_test()
            return
        if self.standby:
            return
        self._run_program(dt)
        self._update_cells()
        self._overflow(dt)
        self._refresh()
        flying = self.program in (63, 64, 65, 66, 70, 71) and not self.lm.landed
        d.comp_acty = self.clock < self.busy_until or (flying and self.rng.random() < 0.35)

    def _run_program(self, dt: float) -> None:
        lm, p, st = self.lm, self.program, self.pstate
        if p == 52:
            if self.clock >= st.get("until", 0):
                if st.get("stage") == "compute":
                    st["stage"] = "n93"
                    self._request(6, 93, flash=True, kind="proceed", comps=(0, 1, 2), regs=(0, 1, 2),
                                  on_pro=self._p52_torque, on_terminate=self._to_p00)
                elif st.get("stage") == "torque":
                    self.log("P52 complete: IMU realigned")
                    self._enter_program(0)
            return
        if p not in (63, 64, 65, 66, 70, 71) or lm.landed:
            return
        tfi = self.clock - self.tig if self.tig is not None else 0.0
        if p == 63:
            stage = st.get("stage")
            if stage == "coast" and tfi >= -35.0:
                st["stage"] = "avg_g"
                self.blank_until = self.clock + 5.0
                self.log("Average-G on; display blanks for 5 s")
            elif stage == "avg_g" and tfi >= -30.0:
                st["stage"] = "v99"
                self.log("FL V99N62: please enable engine ignition (PRO)")
                self._request(99, 62, flash=True, kind="proceed", comps=(0, 1, 2), regs=(0, 1, 2),
                              on_pro=self._p63_arm, on_terminate=self._to_p00)
            elif stage == "armed" and tfi >= 0.0:
                self._ignite()
            elif stage == "burn":
                self._braking_guidance(fixed=0.10)
                if tfi >= 26.0:
                    st["stage"] = "guided"
                    self.tgo = BRAKING_TGO
                    self.log("Throttle up: FTP", level="alarm")
            elif stage == "guided":
                self.tgo -= dt
                self.guidance_timer -= dt
                if self.guidance_timer <= 0:
                    self.guidance_timer = 2.0
                    self._braking_guidance()
                if self.tgo <= 0 or lm.h <= HI_GATE_ALT:
                    self.tgo = 0.0
                    self._enter_program(64)
        elif p == 64:
            self.ttg -= dt
            self.guidance_timer -= dt
            if self.guidance_timer <= 0:
                self.guidance_timer = 1.0
                self._approach_guidance()
            if self.ttg <= 0:
                self.ttg = 0.0
                self._enter_program(65)
        elif p in (65, 66):
            lm.command_rate_of_descent(self.vh_cmd)
        elif p in (70, 71):
            ax = -(5_500.0 + lm.vx) / 60.0
            vh_t = 120.0 if lm.h < 60_000.0 else 0.0
            ah = (vh_t - lm.vh) / 10.0
            lm.command_accel(ax, ah)
            if lm.h > 60_000.0 and -lm.vx > 5_400.0:
                lm.engine_on = False
                self.log("Abort complete: in orbit")
                self._enter_program(0)
                return
        lm.step(dt)
        if lm.contact and not st.get("contact"):
            st["contact"] = True
            self.log("LUNAR CONTACT light", level="alarm")
        if lm.landed:
            hard = abs(lm.touchdown_vh) > 10.0
            self.log(
                f"TOUCHDOWN: {abs(lm.touchdown_vh):.1f} ft/s vertical, {abs(lm.touchdown_vx):.1f} ft/s "
                f"forward, {lm.fuel:.0f} lb propellant left{' - HARD LANDING' if hard else ''}",
                level="alarm",
            )
            self._enter_program(68)

    def _overflow(self, dt: float) -> None:
        loaded = self.rr_switch != "LGC" and self.program in (63, 64, 65, 66) and self.lm.engine_on
        if not loaded:
            self.overflow_timer = 30.0
            return
        self.overflow_timer -= dt
        if self.overflow_timer <= 0:
            code = 0o1202 if self.rng.random() < 0.7 else 0o1201
            self.alarm(code)
            self._restart("executive overflow, rendezvous radar counters")
            self.overflow_timer = self.rng.uniform(20.0, 45.0)

    # ------------------------------------------------------------------ state export

    def to_dict(self) -> dict:
        painted = self.painted
        return {
            "get": round(self.clock, 2),
            "get_text": fmt_get(self.clock),
            "display": self.display.to_dict(),
            "program": self.program,
            "program_name": PROGRAMS.get(self.program, ""),
            "stage": self.pstate.get("stage"),
            "standby": self.standby,
            "failreg": [f"{c:05o}" for c in self.failreg],
            "alarms": [
                {"code": f"{c:05o}", "text": ALARMS.get(c, "")} for c in self.failreg if c
            ],
            "program_request": self.prog_request.to_dict() if self.prog_request else None,
            "operator_request": self.op_request.to_dict() if self.op_request else None,
            "painted_by": painted.source if painted else None,
            "key_rel_pending": self.deferred,
            "keyboard": self.pinball.to_dict(),
            "rr_switch": self.rr_switch,
            "tig": fmt_get(self.tig) if self.tig is not None else None,
            "tfi": round(self.clock - self.tig, 1) if self.tig is not None else None,
            "tgo": round(self.tgo, 1),
            "ttg": round(self.ttg, 1),
            "vh_cmd": self.vh_cmd,
            "lm": self.lm.to_dict(),
            "events": list(self.events)[-60:],
        }
