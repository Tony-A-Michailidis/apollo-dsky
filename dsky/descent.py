"""A small planar model of the LM powered descent, enough for P63/P64/P65/P66 to show
believable numbers on the DSKY. Units are feet, seconds and pounds, as the AGC used.

Frame: x is the ground distance still to go to the landing site (positive while short of
it), h is altitude above the site. vx is negative while the LM is closing on the site.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

G_MOON = 5.32  # ft/s^2 near the surface
R_MOON = 5_702_000.0  # ft
MAX_THRUST = 10_500.0  # lbf, DPS rated thrust
FTP_THRUST = 9_870.0  # lbf, the fixed throttle point (~94%) used through most of P63
MIN_THROTTLE = 0.10
MAX_VAR_THROTTLE = 0.60  # the DPS was throttleable only between 10% and ~60%
ISP = 311.0  # s
G0 = 32.174
FT_PER_NMI = 6076.1
FT_PER_DEG_LON = 99_500.0  # at the lunar equator
PROBE_LENGTH = 5.6  # ft; the contact probes hang below the footpads

SITE_LAT = 0.674  # Tranquility Base
SITE_LON = 23.473


def quadratic_guidance(r: float, v: float, r_t: float, v_t: float, T: float) -> float:
    """Apollo-style explicit (quadratic) guidance for one axis: the constant jerk
    acceleration profile that reaches position r_t with velocity v_t in T seconds."""
    T = max(T, 8.0)
    return 6.0 * (r_t - r) / (T * T) - 4.0 * v / T - 2.0 * v_t / T


@dataclass
class LM:
    x: float = 1_580_000.0  # ~260 nmi short of the site at PDI
    h: float = 50_000.0
    vx: float = -5_560.0
    vh: float = -3.0
    mass: float = 33_500.0
    fuel: float = 17_500.0  # usable DPS propellant
    engine_on: bool = False
    throttle: float = 0.0  # fraction of MAX_THRUST
    ux: float = 0.0  # thrust direction (unit vector); +ux pushes away from the site
    uh: float = 1.0
    t_burn: float = 0.0
    dv_acc: float = 0.0
    contact: bool = False
    landed: bool = False
    touchdown_vh: float = 0.0
    touchdown_vx: float = 0.0
    fuel_low: bool = False
    # Navigation error: what the PGNS thinks the altitude is minus the truth. The Apollo 11
    # state vector was off by a few thousand feet until landing radar updates were allowed.
    alt_err: float = 2_900.0
    lr_permit: bool = False
    site_shift: float = 0.0  # ft; positive moves the target site further downrange
    history: list = field(default_factory=list)

    # ------------------------------------------------------------------ derived

    @property
    def pitch(self) -> float:
        """Thrust axis angle from the local vertical, degrees (0 = straight up)."""
        return math.degrees(math.atan2(self.ux, self.uh))

    @property
    def thrust(self) -> float:
        return self.throttle * MAX_THRUST if self.engine_on and self.fuel > 0 else 0.0

    @property
    def computed_h(self) -> float:
        return self.h + self.alt_err

    @property
    def lr_locked(self) -> bool:
        return self.h < 40_000.0 and not self.landed

    @property
    def dalt(self) -> float:
        """Landing radar altitude minus PGNS computed altitude (N63 R1 / N68 R3)."""
        return -self.alt_err if self.lr_locked else 0.0

    @property
    def vabs(self) -> float:
        return math.hypot(self.vx, self.vh)

    @property
    def range_site_nmi(self) -> float:
        return math.hypot(self.x, self.h) / FT_PER_NMI

    @property
    def lpd_angle(self) -> float:
        """Elevation angle from the LM down to the (shifted) landing site, degrees."""
        return math.degrees(math.atan2(self.h, max(self.x - self.site_shift, 1.0)))

    @property
    def lat(self) -> float:
        return SITE_LAT

    @property
    def lon(self) -> float:
        return SITE_LON - self.x / FT_PER_DEG_LON

    @property
    def a_env_h(self) -> float:
        """Vertical acceleration with the engine off: gravity less centrifugal relief."""
        return -G_MOON + self.vx * self.vx / R_MOON

    @property
    def fuel_seconds(self) -> float:
        """Burn time left at the current throttle."""
        f = self.thrust
        return self.fuel / (f / ISP) if f > 0 else float("inf")

    # ------------------------------------------------------------------ commands

    def command_accel(self, ax: float, ah: float, fixed_throttle: float | None = None) -> None:
        """Point the engine so the total acceleration approaches (ax, ah) and pick a
        throttle the DPS can actually deliver."""
        tx = ax
        th = ah - self.a_env_h
        mag = math.hypot(tx, th)
        if mag < 1e-6:
            self.ux, self.uh = 0.0, 1.0
        else:
            self.ux, self.uh = tx / mag, th / mag
        if fixed_throttle is not None:
            self.throttle = fixed_throttle
            return
        force = self.mass * mag / G0
        frac = force / MAX_THRUST
        if frac > MAX_VAR_THROTTLE:
            frac = FTP_THRUST / MAX_THRUST  # above the throttleable band only FTP is available
        frac = max(MIN_THROTTLE, min(frac, FTP_THRUST / MAX_THRUST))
        self.throttle = frac

    def command_rate_of_descent(self, vh_cmd: float, tau: float = 1.5) -> None:
        """P65/P66: throttle to hold a commanded descent rate, hold the thrust axis near
        vertical while the horizontal velocity is nulled."""
        ah = (vh_cmd - self.vh) / tau
        ax = -self.vx / 6.0  # the crew nulls forward velocity by pitching; model it as a gentle servo
        ax = max(-2.0, min(2.0, ax))
        self.command_accel(ax, ah)
        self.throttle = max(MIN_THROTTLE, min(self.throttle, MAX_VAR_THROTTLE))

    # ------------------------------------------------------------------ physics

    def step(self, dt: float) -> None:
        if self.landed:
            return
        sub = max(1, int(math.ceil(dt / 0.05)))
        h_step = dt / sub
        for _ in range(sub):
            thrust = self.thrust
            if thrust > 0:
                a = thrust * G0 / self.mass
                ax, ah = a * self.ux, a * self.uh
                burned = thrust / ISP * h_step
                self.fuel = max(0.0, self.fuel - burned)
                self.mass -= burned
                self.t_burn += h_step
                self.dv_acc += a * h_step
            else:
                ax, ah = 0.0, 0.0
            ah += self.a_env_h
            self.vx += ax * h_step
            self.vh += ah * h_step
            self.x += self.vx * h_step
            self.h += self.vh * h_step
            if self.lr_permit and self.lr_locked:
                self.alt_err *= math.exp(-h_step / 10.0)
            if not self.contact and self.h <= PROBE_LENGTH:
                self.contact = True
            if self.h <= 0.0:
                self.h = 0.0
                self.landed = True
                self.touchdown_vh = self.vh
                self.touchdown_vx = self.vx
                self.vh = 0.0
                self.vx = 0.0
                self.engine_on = False
                self.throttle = 0.0
                break
        self.fuel_low = self.fuel < 1_200.0

    def to_dict(self) -> dict:
        return {
            "x_ft": round(self.x, 1),
            "h_ft": round(self.h, 1),
            "computed_h_ft": round(self.computed_h, 1),
            "vx_fps": round(self.vx, 2),
            "vh_fps": round(self.vh, 2),
            "vabs_fps": round(self.vabs, 1),
            "mass_lb": round(self.mass, 1),
            "fuel_lb": round(self.fuel, 1),
            "fuel_seconds": None if self.fuel_seconds == float("inf") else round(self.fuel_seconds, 1),
            "fuel_low": self.fuel_low,
            "engine_on": self.engine_on,
            "throttle_pct": round(self.throttle * 100, 1),
            "pitch_deg": round(self.pitch, 1),
            "t_burn_s": round(self.t_burn, 1),
            "dv_acc_fps": round(self.dv_acc, 1),
            "lr_locked": self.lr_locked,
            "lr_permit": self.lr_permit,
            "alt_err_ft": round(self.alt_err, 1),
            "contact": self.contact,
            "landed": self.landed,
            "touchdown_vh_fps": round(self.touchdown_vh, 2),
            "touchdown_vx_fps": round(self.touchdown_vx, 2),
            "range_site_nmi": round(self.range_site_nmi, 2),
            "lpd_deg": round(self.lpd_angle, 1),
            "site_shift_ft": round(self.site_shift, 1),
        }
