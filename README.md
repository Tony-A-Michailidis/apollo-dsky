# Apollo DSKY

A working simulator of the Apollo Guidance Computer display and keyboard, the **DSKY**, with the
Lunar Module flavour of the software (Luminary) behind it, and a web interface that draws the real panel.

It is built in three layers so each can be swapped later:

| Layer | Module | What it is |
|---|---|---|
| Keyboard and display rules | `dsky/pinball.py`, `dsky/display.py`, `dsky/keys.py` | The 19 keys, the verb/noun grammar, data loads, CLR/KEY REL/RSET/PRO, OPR ERR, flashing, lamps. Named after the AGC routine that did this job, *Pinball Game Buttons and Lights*. |
| The computer | `dsky/agc.py`, `dsky/nouns.py`, `dsky/verbs.py`, `dsky/descent.py` | Verb and noun tables with the real display formats, programs P00/P06/P52/P63/P64/P65/P66/P68/P70/P71, alarm registers, software restarts, and a small planar model of the powered descent so the numbers on the panel are real. |
| Web interface | `dsky/server.py`, `dsky/static/` | FastAPI plus a WebSocket. The page draws the electroluminescent segments and the lamp panel, takes keys by mouse or keyboard, and has a side panel for the switches a crew had that were not DSKY keys. |

The HTTP API is small and deliberately machine-friendly, so a script, a "ground station" or an
AI copilot can key the DSKY and read it back without touching the UI.

## Run it

Python 3.11 or newer. On this machine Python lives in WSL, so:

```bash
python3 -m venv ~/venvs/apollo-dsky && source ~/venvs/apollo-dsky/bin/activate
cd /mnt/c/Users/tonym/Downloads/apollo-dsky
pip install -e ".[dev]"
dsky                      # or: python -m dsky --port 8000
```

Open http://127.0.0.1:8000/. The headless trajectory printer is handy while tuning:

```bash
python tools/trace_descent.py            # automatic landing, prints every 20 s
python tools/trace_descent.py --rr AUTO  # with the Apollo 11 executive overflow alarms
pytest                                   # 33 tests
```

To set up the panel for a screenshot, see [SCREENSHOT.md](SCREENSHOT.md).

## Fly the landing

The sim starts at 102:30:00 GET, three minutes before the Apollo 11 PDI, with the LM in P00.
The cue card in the side panel walks through it; the short form:

1. `V37E63E`. P63 flashes V06N61 (time to go, time from ignition, crossrange). `PRO`.
2. At TIG−35 s the display blanks for five seconds (average-G on). At TIG−30 s `FL V99N62` asks to
   enable the engine. `PRO`. Ignition at 10 %, throttle-up to the fixed throttle point at TIG+26 s.
3. The program shows V06N62. Key `V16N68E` to monitor slant range, time to go and the landing radar
   delta-H, as Aldrin did.
4. Below 40,000 ft the landing radar locks. N68 R3 shows the radar disagrees with the computer by
   about 2,900 ft, the Apollo 11 state vector error. `V57E` lets the computer use the radar.
5. Put the rendezvous radar switch in **AUTO TRACK** if you want the 1202 alarms. On an alarm the
   PROG lamp lights and the display is re-established by the restart. `V05N09E` reads the codes,
   `RSET` clears the lamp, `KEY REL` gives the display back to the program.
6. High gate at about 7,500 ft: P64 comes up by itself with N64 (time to go and LPD angle, altitude
   rate, altitude). LPD clicks move the landing site.
7. A ROD click in P64 or P65 takes you into P66. Each click is 1 ft/s. Hold about −3 ft/s for the last
   hundred feet. **LUNAR CONTACT**, then **ENGINE STOP**.
8. P68 flashes V06N43 (latitude, longitude, altitude) to confirm the landing. `PRO`.

Left alone after step 2, P63, P64 and P65 land the vehicle automatically at 3 ft/s with roughly
1,200 lb of propellant left, which is close to the real figures.

Other things that work: `V35E` lamp test, `V16N36E` the clock, `V37E52E` an abbreviated IMU realign,
`V37E06E` standby, `V01N01E 00025E` peek at the TIME1 erasable, `V21N01E 01000E 12345E` poke one,
`V25N69E` landing site correction, `V25N33E` load the ignition time, `V69E` restart, `V36E` fresh
start, V34 to terminate a flashing request, V32 to recycle one. Asking for a program the computer will
not run now (P63 with the engine burning, say) gives program alarm 01520, as it did on the real machine.

## Keyboard

Mouse on the panel, or: `V` `N` digits `+` `-` `Enter`=ENTR `Backspace`=CLR `P`=PRO `K`=KEY REL `R`=RSET.

## API

```
GET  /api/state                 display, lamps, program, alarms, what the computer is waiting for, telemetry
POST /api/key    {"key": "VERB"}
POST /api/keys   {"sequence": "V16N68E", "uplink": false}     cue-card shorthand; uplink=true lights UPLINK ACTY
POST /api/sim    {"rr_switch": "AUTO"} | {"rod": 1} | {"lpd": -1} | {"engine_stop": true} |
                 {"abort": true} | {"abort_stage": true} | {"rate": 4} | {"paused": true} | {"reset": true}
GET  /api/nouns  /api/verbs  /api/programs  /api/alarms  /api/events
WS   /ws                        state pushed every 250 ms and after every key; accepts {"key"} and {"sequence"}
```

`program_request.waiting_for` in the state is `"PRO"` or `"data"` when a flashing display wants a
human decision. That field is the hook for a copilot: it can key anything through the uplink, and the
design intent is that it never presses PRO or ENTR on a flashing request itself.

## What is faithful and what is not

Faithful: the key grammar and error rules, the display formats and scaling of the nouns, the verb
numbers, the display ownership rules (KEY REL lamp when a program wants the panel while you are mid-entry,
operator monitors persisting until the program asks for something new), alarm codes and FAILREG, the
P63 event sequence (N61, average-G blank, V99, 10 % start, throttle-up at +26 s), the executive overflow
alarms when the rendezvous radar is not in LGC, and the broad shape of the Apollo 11 descent.

Simplified: the guidance is a textbook quadratic law in two dimensions rather than the real P63/P64
targeting; the LPD angle is a plain elevation angle; P52, P06, P70 and P71 are sketches; there is no
attitude dynamics, no IMU, no rendezvous radar data, and the crossrange is cosmetic. None of the
original AGC code runs here. If you want that, the Virtual AGC project runs the real Luminary binary,
and the HTTP layer of this project was kept separate from the keyboard layer so it could sit in front of
that emulator instead.
