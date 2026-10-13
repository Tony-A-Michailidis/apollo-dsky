"""FastAPI app: serves the DSKY front end, takes keystrokes, streams state over a WebSocket.

The HTTP API is deliberately small and machine-friendly so that something other than a
human (a ground station, a script, an AI copilot) can key the DSKY and read it back:

    GET  /api/state            everything: display, lamps, program, alarms, telemetry
    POST /api/key              {"key": "VERB"}            one key
    POST /api/keys             {"sequence": "V16N68E", "uplink": false}
    POST /api/sim              crew switches that are not DSKY keys, and sim controls
    GET  /api/nouns /api/verbs /api/programs /api/alarms   the tables
    WS   /ws                   state pushed every tick and after every key
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .agc import AGC, ALARMS, PROGRAMS
from .keys import parse_key, parse_sequence
from .nouns import NOUNS
from .verbs import VERBS

STATIC = Path(__file__).parent / "static"
TICK = 0.25  # seconds of wall clock per tick


class Sim:
    def __init__(self) -> None:
        self.agc = AGC()
        self.rate = 1.0
        self.paused = False
        self.lock = asyncio.Lock()
        self.clients: set[WebSocket] = set()
        self.task: asyncio.Task | None = None

    def snapshot(self) -> dict:
        d = self.agc.to_dict()
        d["rate"] = self.rate
        d["paused"] = self.paused
        d["version"] = __version__
        return d

    async def broadcast(self) -> None:
        if not self.clients:
            return
        payload = json.dumps(self.snapshot())
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def run(self) -> None:
        while True:
            await asyncio.sleep(TICK)
            async with self.lock:
                if not self.paused:
                    self.agc.tick(TICK * self.rate)
            await self.broadcast()


sim = Sim()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    sim.task = asyncio.create_task(sim.run())
    try:
        yield
    finally:
        sim.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sim.task


app = FastAPI(title="Apollo DSKY", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class KeyIn(BaseModel):
    key: str


class KeysIn(BaseModel):
    sequence: str
    uplink: bool = False


class SimIn(BaseModel):
    rr_switch: str | None = None
    rod: int | None = None
    lpd: int | None = None
    engine_stop: bool | None = None
    abort: bool | None = None
    abort_stage: bool | None = None
    rate: float | None = None
    paused: bool | None = None
    reset: bool | None = None


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/state")
async def state():
    return sim.snapshot()


@app.post("/api/key")
async def key(body: KeyIn):
    try:
        k = parse_key(body.key)
    except ValueError as e:
        raise HTTPException(400, str(e))
    async with sim.lock:
        sim.agc.press(k)
    await sim.broadcast()
    return sim.snapshot()


@app.post("/api/keys")
async def keys(body: KeysIn):
    try:
        parse_sequence(body.sequence)
    except ValueError as e:
        raise HTTPException(400, str(e))
    async with sim.lock:
        if body.uplink:
            sim.agc.uplink(body.sequence)
        else:
            sim.agc.press_sequence(body.sequence)
    await sim.broadcast()
    return sim.snapshot()


@app.post("/api/sim")
async def sim_control(body: SimIn):
    async with sim.lock:
        agc = sim.agc
        if body.reset:
            sim.agc = AGC()
            sim.rate = 1.0
            sim.paused = False
            agc = sim.agc
        if body.rr_switch is not None:
            try:
                agc.set_rr_switch(body.rr_switch)
            except ValueError as e:
                raise HTTPException(400, str(e))
        if body.rod:
            agc.rod_click(1 if body.rod > 0 else -1)
        if body.lpd:
            agc.redesignate(body.lpd)
        if body.engine_stop:
            agc.engine_stop()
        if body.abort:
            agc.abort(stage=False)
        if body.abort_stage:
            agc.abort(stage=True)
        if body.rate is not None:
            sim.rate = max(0.25, min(16.0, body.rate))
        if body.paused is not None:
            sim.paused = body.paused
    await sim.broadcast()
    return sim.snapshot()


@app.get("/api/nouns")
async def nouns():
    return [n.to_dict() for n in NOUNS.values()]


@app.get("/api/verbs")
async def verbs():
    return [v.to_dict() for v in VERBS.values()]


@app.get("/api/programs")
async def programs():
    return [{"number": k, "name": v} for k, v in PROGRAMS.items()]


@app.get("/api/alarms")
async def alarms():
    return [{"code": f"{k:05o}", "text": v} for k, v in ALARMS.items()]


@app.get("/api/events")
async def events():
    return list(sim.agc.events)


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    sim.clients.add(websocket)
    try:
        await websocket.send_text(json.dumps(sim.snapshot()))
        while True:
            msg = await websocket.receive_text()
            # Keys may also be sent over the socket: {"key": "ENTR"} or {"sequence": "V16N68E"}
            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                continue
            async with sim.lock:
                if "key" in data:
                    with contextlib.suppress(ValueError):
                        sim.agc.press(parse_key(data["key"]))
                elif "sequence" in data:
                    with contextlib.suppress(ValueError):
                        sim.agc.press_sequence(data["sequence"])
            await sim.broadcast()
    except WebSocketDisconnect:
        pass
    finally:
        sim.clients.discard(websocket)
