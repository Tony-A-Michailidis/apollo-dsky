"""Fly the automatic descent headless and print the trajectory. Development aid.

    python tools/trace_descent.py [--rr AUTO] [--no-v57]
"""

import argparse

from dsky.agc import AGC
from dsky.keys import Key


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rr", default="LGC")
    p.add_argument("--no-v57", action="store_true")
    p.add_argument("--every", type=float, default=20.0)
    args = p.parse_args()

    a = AGC(seed=1)
    a.press_sequence("V37E63EP")
    for _ in range(int((a.tig_lead - 30 + 0.5) / 0.25)):
        a.tick(0.25)
    a.press(Key.PRO)
    if not args.no_v57:
        a.press_sequence("V57E")
    a.set_rr_switch(args.rr)
    t = 0.0
    while not a.lm.landed and t < 1200:
        a.tick(0.25)
        t += 0.25
        every = 5.0 if a.program in (64, 65, 66) else args.every
        if abs(t % every) < 0.01:
            lm = a.lm
            print(
                f"t={t:5.0f} P{a.program} {str(a.pstate.get('stage') or ''):7s} tgo={a.tgo:4.0f} ttg={a.ttg:4.0f} "
                f"x={lm.x:9.0f} h={lm.h:7.0f} vx={lm.vx:7.1f} vh={lm.vh:6.1f} thr={lm.throttle * 100:4.0f}% "
                f"pitch={lm.pitch:5.1f} fuel={lm.fuel:6.0f}"
            )
    lm = a.lm
    print(f"landed={lm.landed} vh={lm.touchdown_vh:.1f} vx={lm.touchdown_vx:.1f} x={lm.x:.0f} fuel={lm.fuel:.0f}")
    for e in list(a.events)[-12:]:
        print(e["get"], e["text"])


if __name__ == "__main__":
    main()
