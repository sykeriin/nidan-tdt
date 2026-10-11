"""Live simulation endpoints: a plant you can inject anomalies into while the twin and analytics watch (SIMULATED).

    POST /api/live/session            start (or restart) the session
    GET  /api/live/stream[?limit=N]   NDJSON, one tick per line {tick, frame, alerts, injections, simulated}
    POST /api/live/inject             {kind, params..., channel?}
    POST /api/live/clear              {id?, kind?}  (no body fields = clear everything)
    POST /api/live/refill             refill the oil (undoes a leak or theft)
    POST /api/live/control            {rate?, paused?}  ticks per second; pause
    GET  /api/live/catalogue          the injectable anomalies and their parameters
    GET  /api/live/state              the last tick

One global session (a demo, not a multi-user service). A new /stream takes over from an older one.
"""
from __future__ import annotations

import json
import threading
import time

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from server.serialize import plain
from sim import live as L

router = APIRouter(prefix="/api/live", tags=["live"])

_lock = threading.Lock()
_session: L.LiveSession | None = None
_control = {"rate": 2.0, "paused": False, "stream": 0}


def _get() -> L.LiveSession:
    global _session
    with _lock:
        if _session is None:
            _session = L.LiveSession()
        return _session


class SessionIn(BaseModel):
    seed: int = 0


class InjectIn(BaseModel):
    kind: str
    channel: str | None = None
    params: dict[str, float] = Field(default_factory=dict)


class ClearIn(BaseModel):
    id: int | None = None
    kind: str | None = None


class ControlIn(BaseModel):
    rate: float | None = Field(None, gt=0, le=20, description="ticks (15 simulated minutes each) per real second")
    paused: bool | None = None


def _info(s: L.LiveSession) -> dict:
    return {"tick_minutes": 15, "i_rated_A": s.i_rated, "params": plain(s.params()), "control": dict(_control),
            "start": s.start.isoformat(), "simulated": True,
            "asset": plain({k: v for k, v in s.asset.items() if k != "tags"})}


@router.get("/catalogue")
def catalogue():
    return {"injections": _catalogue_list(), "sensors": L.SENSORS}


def _catalogue_list() -> list[dict]:
    return [{"kind": k, **v} for k, v in L.CATALOGUE.items()]


@router.post("/session")
def new_session(body: SessionIn | None = None):
    global _session
    with _lock:
        _session = L.LiveSession(seed=(body.seed if body else 0))
        _control["stream"] += 1
        return _info(_session)


@router.get("/info")
def info():
    return _info(_get())


@router.get("/state")
def state():
    s = _get()
    return plain(s.last) if s.last else {"detail": "no tick yet"}


@router.post("/inject")
def inject(body: InjectIn):
    params = dict(body.params)
    if body.channel:
        params["channel"] = body.channel
    return _get().inject(body.kind, **params)


@router.post("/clear")
def clear(body: ClearIn | None = None):
    b = body or ClearIn()
    return {"removed": _get().clear(injection_id=b.id, kind=b.kind)}


@router.post("/refill")
def refill():
    _get().refill_oil()
    return {"ok": True}


@router.post("/control")
def control(body: ControlIn):
    if body.rate is not None:
        _control["rate"] = body.rate
    if body.paused is not None:
        _control["paused"] = body.paused
    return dict(_control)


@router.get("/stream")
def stream(limit: Annotated[int | None, Query(ge=1, le=100000, description="stop after this many ticks; omit to run until the client leaves")] = None):
    s = _get()
    with _lock:
        _control["stream"] += 1
        me = _control["stream"]

    def lines():
        sent = 0
        while _control["stream"] == me and (limit is None or sent < limit):
            if _control["paused"]:
                time.sleep(0.1)
                continue
            t0 = time.time()
            yield json.dumps(plain(s.tick())) + "\n"
            sent += 1
            time.sleep(max(0.0, 1.0 / _control["rate"] - (time.time() - t0)))
    return StreamingResponse(lines(), media_type="application/x-ndjson")
