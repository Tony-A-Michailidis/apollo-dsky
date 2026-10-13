"""Programs, alarms and the descent: from V37E63E to lunar contact."""

from dsky.agc import AGC
from dsky.keys import Key


def run(a: AGC, seconds: float, dt: float = 0.25) -> None:
    n = int(seconds / dt)
    for _ in range(n):
        a.tick(dt)


def fly_to_ignition(a: AGC) -> None:
    a.press_sequence("V37E63E")
    a.press(Key.PRO)  # accept N61
    run(a, a.tig_lead - 30.0 + 0.5)  # past average-G blank, V99 is flashing
    assert a.display.verb == "99" and a.display.flash
    a.press(Key.PRO)  # enable ignition
    assert a.armed
    run(a, 31.0)
    assert a.lm.engine_on


def test_p63_sequence_to_throttle_up():
    a = AGC(seed=1)
    fly_to_ignition(a)
    assert a.display.verb == "06" and a.display.noun == "62"
    assert abs(a.lm.throttle - 0.10) < 1e-6
    run(a, 27.0)
    assert a.pstate["stage"] == "guided"
    assert a.lm.throttle > 0.9  # FTP


def test_v99_not_proceeded_means_no_ignition():
    a = AGC(seed=1)
    a.press_sequence("V37E63EP")
    run(a, a.tig_lead + 10.0)
    assert not a.lm.engine_on and a.display.verb == "99" and a.display.flash
    a.press(Key.PRO)
    run(a, 0.5)
    assert a.lm.engine_on  # late PRO ignites immediately


def test_p63_not_permitted_with_engine_running_raises_1520():
    a = AGC(seed=1)
    fly_to_ignition(a)
    a.press_sequence("V37E63E")
    assert a.failreg[2] == 0o1520 and a.display.lamps["PROG"]
    assert a.program == 63


def test_rendezvous_radar_switch_causes_1202_alarms():
    a = AGC(seed=3)
    fly_to_ignition(a)
    a.set_rr_switch("AUTO")
    a.press_sequence("V16N68E")
    run(a, 60.0)
    assert a.failreg[2] in (0o1201, 0o1202)
    assert a.display.lamps["PROG"]
    # the restart put the program display back
    assert a.display.noun == "62"
    a.press_sequence("V05N09E")
    assert a.display.r3.digits in ("01201", "01202")
    a.press(Key.RSET)
    assert not a.display.lamps["PROG"]
    a.set_rr_switch("LGC")
    before = list(a.failreg)
    run(a, 90.0)
    assert a.failreg == before


def test_landing_radar_delta_h_until_v57():
    a = AGC(seed=1)
    fly_to_ignition(a)
    while a.lm.h >= 40_000:
        a.tick(0.25)
    run(a, 2.0)
    assert a.lm.lr_locked
    a.press_sequence("V16N68E")
    assert a.display.r3.sign == "-" and int(a.display.r3.digits) > 2000  # LR says we are lower
    a.press_sequence("V57E")
    assert a.lm.lr_permit
    run(a, 60.0)
    assert abs(a.lm.alt_err) < 50


def test_full_automatic_landing():
    a = AGC(seed=1)
    fly_to_ignition(a)
    a.press_sequence("V57E")
    run(a, 1200.0)
    lm = a.lm
    assert lm.landed, (lm.h, lm.vh, lm.vx, a.program)
    assert abs(lm.touchdown_vh) < 10.0, lm.touchdown_vh
    assert abs(lm.touchdown_vx) < 10.0, lm.touchdown_vx
    assert lm.fuel > 300.0, lm.fuel
    assert a.program == 68 and a.display.noun == "43" and a.display.flash
    a.press(Key.PRO)
    assert a.program == 0


def test_p66_rate_of_descent_and_engine_stop():
    a = AGC(seed=1)
    fly_to_ignition(a)
    a.press_sequence("V57E")
    while a.program != 64:
        a.tick(0.25)
    assert a.display.noun == "64"
    run(a, 60.0)
    a.rod_click(-1)  # take over
    assert a.program == 66 and a.display.noun == "60"

    def target(h: float) -> float:  # a sensible rate-of-descent schedule
        return -20.0 if h > 600 else -10.0 if h > 200 else -3.0

    while not a.lm.contact and not a.lm.landed:
        a.tick(0.25)
        want = target(a.lm.h)
        if a.vh_cmd < want:
            a.rod_click(1)
        elif a.vh_cmd > want:
            a.rod_click(-1)
    a.engine_stop()
    run(a, 10.0)
    # Engine off at probe contact: the LM drops the last 5.6 ft, which adds ~7.7 ft/s at lunar g.
    assert a.lm.landed and abs(a.lm.touchdown_vh) < 10.0, a.lm.touchdown_vh
    assert a.lm.fuel > 0


def test_abort_climbs_to_orbit():
    a = AGC(seed=1)
    fly_to_ignition(a)
    run(a, 120.0)
    a.abort()
    assert a.program == 70
    run(a, 600.0)
    assert a.program == 0 and not a.lm.engine_on and a.lm.h > 60_000


def test_p06_standby_and_resume():
    a = AGC(seed=1)
    a.press_sequence("V37E06E")
    assert a.display.verb == "50" and a.display.noun == "25" and a.display.r1.digits == "00062"
    a.press(Key.PRO)
    assert a.standby and a.display.lamps["STBY"] and a.display.prog == "  "
    a.press_sequence("V16N36E")  # keyboard is dead in standby
    assert a.display.verb == "  "
    a.press(Key.PRO)
    assert not a.standby and a.display.prog == "06"


def test_p52_realign_runs_to_completion():
    a = AGC(seed=1)
    a.press_sequence("V37E52E")
    assert a.display.verb == "04" and a.display.noun == "06" and a.display.flash
    a.press(Key.PRO)
    run(a, 3.5)
    assert a.display.noun == "93" and a.display.flash
    a.press(Key.PRO)
    run(a, 2.5)
    assert a.program == 0


def test_tig_can_be_loaded_with_v25n33():
    a = AGC(seed=1)
    a.press_sequence("V37E63E")
    a.press_sequence("V25N33E+00102E+00040E+00000E")
    assert a.tig == 102 * 3600 + 40 * 60
    a.press(Key.KEY_REL)
    assert a.display.noun == "61" and a.display.flash


def test_state_export_is_json_friendly():
    import json

    a = AGC(seed=1)
    a.press_sequence("V16N36E")
    s = json.loads(json.dumps(a.to_dict()))
    assert s["display"]["verb"] == "16" and s["program"] == 0
    assert s["operator_request"]["noun"] == 36
