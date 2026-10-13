"""Noun table and register formats, modelled on Luminary 099 (the Apollo 11 LM program).

A noun names up to three quantities. Each component has a display format that fixes the
scale and the implied decimal point, exactly as the crew cue cards wrote them:
"XXXXX." feet, "XXXX.X" nautical miles, "0XX.XX" seconds, "MMBSS" minutes-blank-seconds.
"""

from __future__ import annotations

from dataclasses import dataclass

# format -> (scale, decimal?) ; scale multiplies the engineering value to get the 5 digits.
_FORMATS: dict[str, tuple[float, bool]] = {
    "octal": (1, False),
    "XXXXX.": (1, True),
    "XXXX.X": (10, True),
    "XXX.XX": (100, True),
    "XX.XXX": (1000, True),
    "00XXX": (1, True),  # hours
    "000XX": (1, True),  # minutes
    "0XX.XX": (100, True),  # seconds
    "MMBSS": (1, True),  # seconds -> minutes, blank, seconds
    "XXBXX": (1, True),  # two small integers (e.g. time-to-go and LPD angle)
}


def is_decimal(fmt: str) -> bool:
    return _FORMATS[fmt][1]


def encode(fmt: str, value) -> tuple[str, str]:
    """Engineering value -> (sign, five display characters)."""
    if fmt == "octal":
        return "", f"{int(value) & 0o77777:05o}"
    if fmt == "MMBSS":
        secs = float(value)
        sign = "-" if secs < 0 else "+"
        secs = abs(secs)
        mm, ss = divmod(int(round(secs)), 60)
        mm = min(mm, 99)
        return sign, f"{mm:02d} {ss:02d}"
    if fmt == "XXBXX":
        a, b = value
        sign = "-" if a < 0 else "+"
        a = min(abs(int(round(a))), 99)
        b = min(abs(int(round(b))), 99)
        return sign, f"{a:02d} {b:02d}"
    scale, _ = _FORMATS[fmt]
    n = int(round(float(value) * scale))
    sign = "-" if n < 0 else "+"
    n = min(abs(n), 99999)
    return sign, f"{n:05d}"


def decode(fmt: str, sign: str, digits: str) -> float:
    """Keyed sign + digits -> engineering value (used by load verbs)."""
    if fmt == "octal":
        return int(digits, 8)
    scale, _ = _FORMATS[fmt]
    if fmt in ("MMBSS", "XXBXX"):
        a, b = int(digits[:2]), int(digits[3:])
        v = a * 60 + b if fmt == "MMBSS" else a
    else:
        v = int(digits) / scale
    return -v if sign == "-" else v


@dataclass(frozen=True)
class Component:
    name: str
    units: str
    fmt: str
    key: str  # erasable cell name resolved by the AGC; "x.h"/"x.m"/"x.s" split a time cell

    @property
    def decimal(self) -> bool:
        return is_decimal(self.fmt)


@dataclass(frozen=True)
class Noun:
    number: int
    name: str
    components: tuple[Component, ...]
    special: str | None = None  # "address" for N01

    @property
    def octal_only(self) -> bool:
        return all(c.fmt == "octal" for c in self.components)

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "name": self.name,
            "components": [
                {"name": c.name, "units": c.units, "format": c.fmt, "key": c.key}
                for c in self.components
            ],
        }


def _time(name: str, key: str) -> tuple[Component, ...]:
    return (
        Component(f"{name} (hours)", "h", "00XXX", f"{key}.h"),
        Component(f"{name} (minutes)", "min", "000XX", f"{key}.m"),
        Component(f"{name} (seconds)", "s", "0XX.XX", f"{key}.s"),
    )


def _n(number: int, name: str, *comps: Component, special: str | None = None) -> Noun:
    return Noun(number, name, tuple(comps), special)


NOUNS: dict[int, Noun] = {
    n.number: n
    for n in [
        _n(
            1,
            "Specify machine address (octal contents)",
            Component("Contents of address", "octal", "octal", "mem.0"),
            Component("Contents of address+1", "octal", "octal", "mem.1"),
            Component("Contents of address+2", "octal", "octal", "mem.2"),
            special="address",
        ),
        _n(5, "Angular error", Component("Angular error", "deg", "XXX.XX", "ang_err")),
        _n(
            6,
            "Option code",
            Component("Option code", "octal", "octal", "opt_code"),
            Component("Option data", "octal", "octal", "opt_data"),
        ),
        _n(
            9,
            "Alarm codes",
            Component("First alarm", "octal", "octal", "failreg.0"),
            Component("Second alarm", "octal", "octal", "failreg.1"),
            Component("Most recent alarm", "octal", "octal", "failreg.2"),
        ),
        _n(
            18,
            "Auto maneuver ball angles",
            Component("Roll", "deg", "XXX.XX", "fdai.r"),
            Component("Pitch", "deg", "XXX.XX", "fdai.p"),
            Component("Yaw", "deg", "XXX.XX", "fdai.y"),
        ),
        _n(
            20,
            "ICDU angles",
            Component("Outer gimbal", "deg", "XXX.XX", "cdu.x"),
            Component("Inner gimbal", "deg", "XXX.XX", "cdu.y"),
            Component("Middle gimbal", "deg", "XXX.XX", "cdu.z"),
        ),
        _n(25, "Checklist code", Component("Checklist item", "octal", "octal", "checklist")),
        _n(33, "Time of ignition", *_time("TIG", "tig")),
        _n(34, "Time of event", *_time("Time of event", "tevent")),
        _n(35, "Time from event", *_time("Time from event", "tfe")),
        _n(36, "Time of AGC clock", *_time("AGC clock", "clock")),
        _n(
            40,
            "Time from ignition / velocity to be gained / delta-V accumulated",
            Component("Time from ignition", "min s", "MMBSS", "tfi"),
            Component("Velocity to be gained", "ft/s", "XXXXX.", "vg"),
            Component("Delta-V accumulated", "ft/s", "XXXXX.", "dv_acc"),
        ),
        _n(
            43,
            "Latitude / longitude / altitude",
            Component("Latitude", "deg", "XXX.XX", "lat"),
            Component("Longitude", "deg", "XXX.XX", "lon"),
            Component("Altitude", "nmi", "XXXX.X", "alt_nmi"),
        ),
        _n(
            44,
            "Apocenter / pericenter / time to free fall",
            Component("Apocenter altitude", "nmi", "XXXX.X", "apo"),
            Component("Pericenter altitude", "nmi", "XXXX.X", "peri"),
            Component("Time to free fall", "min s", "MMBSS", "tff"),
        ),
        _n(
            60,
            "Forward velocity / altitude rate / altitude",
            Component("Forward velocity", "ft/s", "XXXXX.", "vfwd"),
            Component("Altitude rate", "ft/s", "XXXXX.", "hdot"),
            Component("Altitude", "ft", "XXXXX.", "h"),
        ),
        _n(
            61,
            "Time to go / time from ignition / crossrange",
            Component("Time to go in braking phase", "min s", "MMBSS", "tgo"),
            Component("Time from ignition", "min s", "MMBSS", "tfi"),
            Component("Crossrange", "nmi", "XXXX.X", "crossrange"),
        ),
        _n(
            62,
            "Absolute velocity / time from ignition / delta-V accumulated",
            Component("Absolute velocity", "ft/s", "XXXXX.", "vabs"),
            Component("Time from ignition", "min s", "MMBSS", "tfi"),
            Component("Delta-V accumulated", "ft/s", "XXXXX.", "dv_acc"),
        ),
        _n(
            63,
            "Delta altitude (LR minus computed) / altitude rate / computed altitude",
            Component("Delta altitude (LR - PGNS)", "ft", "XXXXX.", "dalt"),
            Component("Altitude rate", "ft/s", "XXXXX.", "hdot"),
            Component("Computed altitude", "ft", "XXXXX.", "h"),
        ),
        _n(
            64,
            "Time to go and LPD angle / altitude rate / altitude",
            Component("Time to go (s) and LPD angle (deg)", "s deg", "XXBXX", "ttg_lpd"),
            Component("Altitude rate", "ft/s", "XXXXX.", "hdot"),
            Component("Altitude", "ft", "XXXXX.", "h"),
        ),
        _n(65, "Sampled AGC time", *_time("Sampled AGC time", "clock")),
        _n(
            66,
            "Landing radar slant range / position",
            Component("LR slant range", "ft", "XXXXX.", "lr_range"),
            Component("LR antenna position", "octal", "octal", "lr_pos"),
        ),
        _n(
            67,
            "Landing radar velocities",
            Component("LR Vx", "ft/s", "XXXXX.", "lr_vx"),
            Component("LR Vy", "ft/s", "XXXXX.", "lr_vy"),
            Component("LR Vz", "ft/s", "XXXXX.", "lr_vz"),
        ),
        _n(
            68,
            "Slant range to landing site / time to go in braking / LR altitude minus computed",
            Component("Slant range to landing site", "nmi", "XXXX.X", "range_site"),
            Component("Time to go in braking phase", "min s", "MMBSS", "tgo"),
            Component("LR altitude minus computed altitude", "ft", "XXXXX.", "dalt"),
        ),
        _n(
            69,
            "Landing site correction",
            Component("Delta Z (downrange)", "ft", "XXXXX.", "lsc.z"),
            Component("Delta Y (crossrange)", "ft", "XXXXX.", "lsc.y"),
            Component("Delta X (altitude)", "ft", "XXXXX.", "lsc.x"),
        ),
        _n(
            74,
            "Time from ignition / yaw / pitch (ascent)",
            Component("Time from ignition", "min s", "MMBSS", "tfi"),
            Component("Yaw", "deg", "XXX.XX", "fdai.y"),
            Component("Pitch", "deg", "XXX.XX", "fdai.p"),
        ),
        _n(
            76,
            "Desired horizontal velocity / desired radial velocity / crossrange (ascent)",
            Component("Desired horizontal velocity", "ft/s", "XXXXX.", "asc_vh"),
            Component("Desired radial velocity", "ft/s", "XXXXX.", "asc_vr"),
            Component("Crossrange", "nmi", "XXXX.X", "crossrange"),
        ),
        _n(
            85,
            "Velocity to be gained, body axes",
            Component("VG X", "ft/s", "XXXXX.", "vg"),
            Component("VG Y", "ft/s", "XXXXX.", "zero"),
            Component("VG Z", "ft/s", "XXXXX.", "zero"),
        ),
        _n(
            92,
            "Desired thrust / altitude rate / computed altitude",
            Component("Desired thrust", "%", "XXXXX.", "throttle_pct"),
            Component("Altitude rate", "ft/s", "XXXXX.", "hdot"),
            Component("Computed altitude", "ft", "XXXXX.", "h"),
        ),
        _n(
            93,
            "Delta gyro angles",
            Component("Delta gyro X", "deg", "XX.XXX", "dgyro.x"),
            Component("Delta gyro Y", "deg", "XX.XXX", "dgyro.y"),
            Component("Delta gyro Z", "deg", "XX.XXX", "dgyro.z"),
        ),
    ]
}
