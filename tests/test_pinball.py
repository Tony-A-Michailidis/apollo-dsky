"""Keyboard and display rules: verbs, nouns, loads, errors, lamps, display ownership."""

from dsky.agc import AGC
from dsky.keys import Key, parse_sequence


def agc():
    return AGC(seed=1)


def show(a: AGC) -> str:
    d = a.display
    return f"V{d.verb} N{d.noun} {d.r1.sign}{d.r1.digits} {d.r2.sign}{d.r2.digits} {d.r3.sign}{d.r3.digits}"


def test_parse_sequence_shorthand():
    assert parse_sequence("V37E63E") == [Key.VERB, Key.D3, Key.D7, Key.ENTR, Key.D6, Key.D3, Key.ENTR]
    assert parse_sequence("v16 n68 e")[0] is Key.VERB


def test_v16n36_shows_the_clock_and_updates():
    a = agc()
    a.press_sequence("V16N36E")
    d = a.display
    assert d.verb == "16" and d.noun == "36" and not d.flash
    assert d.r1.digits == "00102" and d.r1.sign == "+"  # 102 hours GET
    assert d.r2.digits == "00030"  # 30 minutes
    before = d.r3.digits
    a.tick(1.5)
    assert d.r3.digits != before  # monitor verbs refresh


def test_v06_is_a_snapshot_not_a_monitor():
    a = agc()
    a.press_sequence("V06N36E")
    before = a.display.r3.digits
    a.tick(2.0)
    assert a.display.r3.digits == before


def test_entr_reuses_displayed_noun_and_verb():
    a = agc()
    a.press_sequence("V16N36E")
    a.press_sequence("V06E")  # new verb, same noun
    assert a.display.verb == "06" and a.display.noun == "36"
    a.press_sequence("N65E")  # new noun, same verb
    assert a.display.verb == "06" and a.display.noun == "65"


def test_undefined_verb_lights_opr_err_and_rset_clears_it():
    a = agc()
    a.press_sequence("V98E")
    assert a.display.lamps["OPR ERR"]
    a.press(Key.RSET)
    assert not a.display.lamps["OPR ERR"]


def test_decimal_display_of_octal_noun_is_an_error():
    a = agc()
    a.press_sequence("V06N09E")
    assert a.display.lamps["OPR ERR"]
    a.press(Key.RSET)
    a.press_sequence("V05N09E")
    assert not a.display.lamps["OPR ERR"]
    assert a.display.r1.digits == "00000" and a.display.r1.sign == ""


def test_three_digit_verb_is_an_error():
    a = agc()
    a.press_sequence("V161")
    assert a.display.lamps["OPR ERR"]


def test_decimal_load_needs_sign_and_five_digits():
    a = agc()
    a.press_sequence("V25N69E")
    assert a.display.flash and a.display.r1.digits == "     "
    a.press_sequence("12345E")  # no sign
    assert a.display.lamps["OPR ERR"]
    a.press(Key.RSET)
    a.press(Key.CLR)  # blank R1 and start again
    a.press_sequence("+00100E")
    assert a.display.r2.digits == "     "  # now loading R2
    a.press_sequence("+00000E+00000E")
    assert not a.display.flash
    assert a.lm.site_shift == 100.0
    assert a.display.r1.digits == "00100"


def test_clr_backs_up_to_previous_register():
    a = agc()
    a.press_sequence("V25N69E+00100E")
    a.press(Key.CLR)  # R2 already blank: back to R1
    assert a.pinball.load.index == 0
    assert a.display.r1.digits == "     "


def test_octal_load_rejects_8_and_sign():
    a = agc()
    a.press_sequence("V21N01E")  # specify address
    assert a.display.flash and a.pinball.entry == "address"
    a.press_sequence("01000E")  # address 01000
    assert a.pinball.entry == "data"
    a.press(Key.D8)
    assert a.display.lamps["OPR ERR"]
    a.press(Key.RSET)
    a.press(Key.PLUS)
    assert a.display.lamps["OPR ERR"]
    a.press(Key.RSET)
    a.press_sequence("12345E")
    assert a.erasable[0o1000] == 0o12345
    a.press_sequence("V01N01E01000E")
    assert a.display.r1.digits == "12345"


def test_v01n01_reads_the_clock_cell():
    a = agc()
    a.press_sequence("V01N01E00025E")
    assert a.display.r1.digits == f"{a.read_erasable(0o25):05o}"


def test_lamp_test_lights_everything_for_five_seconds():
    a = agc()
    a.press_sequence("V16N36E")
    a.press_sequence("V35E")
    d = a.display
    assert all(d.lamps.values()) and d.r1.digits == "88888" and d.verb == "88"
    a.tick(6.0)
    assert not any(d.lamps.values())
    assert d.verb == "16" and d.noun == "36" and d.prog == "00"


def test_fresh_start_clears_alarms():
    a = agc()
    a.alarm(0o1202)
    assert a.display.lamps["PROG"] and a.failreg[0] == 0o1202
    a.press_sequence("V36E")
    assert a.failreg == [0, 0, 0] and not a.display.lamps["PROG"] and a.program == 0


def test_v37_with_bad_program_is_opr_err():
    a = agc()
    a.press_sequence("V37E99E")
    assert a.display.lamps["OPR ERR"]
    assert a.program == 0 and not a.display.flash


def test_key_rel_lamp_when_program_asks_mid_entry():
    a = agc()
    a.press_sequence("V37E63E")  # P63: FL V06N61 waiting for PRO
    assert a.display.verb == "06" and a.display.noun == "61" and a.display.flash
    a.press(Key.PRO)
    assert not a.display.flash and a.pstate["stage"] == "coast"
    a.press_sequence("V16N6")  # operator mid-entry
    a.tick(a.tig_lead - 35.0 + 0.5)  # program now wants to blank for average-G, then FL V99
    a.tick(5.5)
    assert a.display.lamps["KEY REL"]  # program request deferred
    a.press_sequence("8E")  # operator finishes: V16N68 up, program still waiting
    assert a.display.verb == "16" and a.display.noun == "68"
    assert a.display.lamps["KEY REL"]
    a.press(Key.KEY_REL)
    assert not a.display.lamps["KEY REL"]
    assert a.display.verb == "99" and a.display.noun == "62" and a.display.flash


def test_program_request_overrides_completed_operator_display():
    a = agc()
    a.press_sequence("V37E63EP")  # select P63 and PRO the first display
    a.press_sequence("V16N68E")
    assert a.display.noun == "68"
    a._restart("test")  # a software restart re-establishes the program display
    assert a.display.verb == "06" and a.display.noun == "61"
