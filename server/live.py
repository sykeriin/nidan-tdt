"""Live simulation endpoints: a plant you can inject anomalies into while the twin and analytics watch (SIMULATED).

    POST /api/live/session            start (or restart) the session
    GET  /api/live/stream[?limit=N]   NDJSON, one tick per line {tick, frame, alerts, injections, simulated}
    POST /api/live/inject             {kind, params..., channel?}
    POST /api/live/clear              {id?, kind?}  (no body fields = clear everything)
    POST /api/live/refill             refill the oil (undoes a leak or theft)
    POST /api/live/control            {rate?, paused?}  ticks per second; pause
    GET  /api/live/catalogue          the injectable anomalies and their parameters
    GET  /api/live/state              the last tick

One global session (a demo, not a multi-user service). A background ticker advances the plant; every /stream, the dashboard
and the phone alerts watch the same ticks, so any number of clients can connect.
"""
from __future__ import annotations

import json
import threading
import time

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from server.serialize import plain
from sim import live as L

router = APIRouter(prefix="/api/live", tags=["live"])

_lock = threading.Lock()
_session: L.LiveSession | None = None
_control = {"rate": 2.0, "paused": False, "stream": 0}
IDLE_S = 45.0              # the ticker rests when no client has asked for live data for this long
_cond = threading.Condition()
_latest: dict = {"seq": 0, "tick": None}
_demand = {"t": 0.0}
_ticker: threading.Thread | None = None
alert_sinks: list = []     # callables taking one alert dict; server.app registers the phone-notification queue here
_announced: dict = {"session": None, "ids": set()}


def _announce(s: L.LiveSession, tick: dict) -> None:
    """Hand each newly raised live alert to the sinks once, so a phone listening to the companion queue is notified when an anomaly is injected on the tablet. Alerts already present when a stream (re)connects are not replayed."""
    first = _announced["session"] is not s
    if first:
        _announced["session"], _announced["ids"] = s, set()
    for a in tick.get("alerts") or []:
        aid = a.get("id")
        if aid in _announced["ids"]:
            continue
        _announced["ids"].add(aid)
        if not first:
            for sink in alert_sinks:
                try:
                    sink(a)
                except Exception:
                    pass


def _ticker_loop() -> None:
    while True:
        if _control["paused"] or time.time() - _demand["t"] > IDLE_S:
            time.sleep(0.2)
            continue
        t0 = time.time()
        try:
            s = _get()
            tk = plain(s.tick())
            _announce(s, tk)
            with _cond:
                _latest["seq"] += 1
                _latest["tick"] = tk
                _cond.notify_all()
        except Exception:
            time.sleep(0.5)
        time.sleep(max(0.0, 1.0 / _control["rate"] - (time.time() - t0)))


def touch() -> None:
    """A client wants live data: start the ticker the first time and keep it running."""
    global _ticker
    _demand["t"] = time.time()
    with _lock:
        if _ticker is None or not _ticker.is_alive():
            _ticker = threading.Thread(target=_ticker_loop, name="live-ticker", daemon=True)
            _ticker.start()


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
    touch()
    with _lock:
        me = _control["stream"]
    with _cond:
        seen = _latest["seq"]

    def lines():
        nonlocal seen
        sent = 0
        while _control["stream"] == me and (limit is None or sent < limit):
            touch()
            with _cond:
                if _latest["seq"] <= seen:
                    _cond.wait(timeout=1.0)
                seq, tk = _latest["seq"], _latest["tick"]
            if seq <= seen or tk is None:
                continue
            seen = seq
            yield json.dumps(tk) + "\n"
            sent += 1
    return StreamingResponse(lines(), media_type="application/x-ndjson")


class ServiceIn(BaseModel):
    action: str = Field(description="dry_oil: dry the oil and replace the silica gel; refill: refill the oil")


@router.post("/service")
def service(body: ServiceIn):
    s = _get()
    if body.action == "dry_oil":
        s.dry_oil()
    elif body.action == "refill":
        s.refill_oil()
    else:
        raise HTTPException(400, "action must be dry_oil or refill")
    return {"ok": True, "action": body.action}


_sync = {"rows": -1, "at": 0.0}


@router.post("/sync")
def sync(force: bool = False):
    """Rebuild the `live` dataset (the simulated transformer as a source) from the session so far. Cheap when nothing changed."""
    from dt import api
    touch()
    s = _get()
    with s.lock:
        n = len(s.history)
        if n < 8:
            raise HTTPException(409, "the live plant has not produced enough readings yet")
        stale = force or n != _sync["rows"] or "live" not in api._MEM
        if stale and (force or time.time() - _sync["at"] > 4.0 or "live" not in api._MEM):
            rows, events = list(s.history), list(s.events)
            asset, caps, ref = dict(s.asset), s.caps, s.ref
        else:
            rows = None
    if rows is not None:
        api.set_live_run(rows, events, caps, asset, ref)
        _sync["rows"], _sync["at"] = n, time.time()
    run = api.get_run("live")
    last = run.trend["timestamp"].iloc[-1]
    return {"dataset_id": "live", "name": run.name, "rows": int(len(run.trend)), "last_timestamp": last.isoformat(),
            "tick": s.n, "simulated": True}


def condition_items() -> list[dict]:
    from analytics.common import load_thresholds
    from twin import condition as C
    s = _get()
    if s.last is None:
        raise HTTPException(409, "the live plant has not produced a reading yet")
    th = load_thresholds(asset=s.asset)
    hist = list(s.history)[-5:]
    rate = None
    if len(hist) >= 5:
        rate = (float(hist[-1]["OTI_C"]) - float(hist[0]["OTI_C"])) / (4 * 0.25)
    return plain(C.board(s.last["frame"], th, s.params(), s.asset, s.events, rate))


def active_injections() -> list[dict]:
    return plain(_get().active())


@router.get("/condition")
def condition():
    """The condition board: every quantity on the engineer's checklist with its limit and status (IS 2026 / IS 1180 / CEA profile)."""
    from analytics.common import load_thresholds
    from twin import condition as C
    touch()
    s = _get()
    if s.last is None:
        raise HTTPException(409, "the live plant has not produced a reading yet")
    th = load_thresholds(asset=s.asset)
    hist = list(s.history)[-5:]
    rate = None
    if len(hist) >= 5:
        rate = (float(hist[-1]["OTI_C"]) - float(hist[0]["OTI_C"])) / (4 * 0.25)
    items = C.board(s.last["frame"], th, s.params(), s.asset, s.events, rate)
    return plain({"timestamp": s.last["frame"]["timestamp"], "standard": "India: IS 2026, IS 1180, IS 6600, IS 1866, CEA", "items": items,
                  "silica_scale": [{"upto": t, "colour": c, "label": l} for t, c, l in C.SILICA_COLOURS]})
