"""HTTP layer of the live simulation: session, stream, inject, clear, control.

The stream is read with ?limit=N: Starlette's TestClient buffers the whole response, so an endless stream would hang.
"""
import json
import warnings

import pytest
from fastapi.testclient import TestClient

from server.app import app

warnings.simplefilter("ignore")


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        client.post("/api/live/control", json={"rate": 20, "paused": False})
        client.post("/api/live/session", json={"seed": 0})
        yield client


def _take(c, n):
    r = c.get(f"/api/live/stream?limit={n}")
    assert r.status_code == 200
    return [json.loads(line) for line in r.text.splitlines() if line]


def test_catalogue_lists_every_anomaly(c):
    cat = c.get("/api/live/catalogue").json()
    kinds = {i["kind"] for i in cat["injections"]}
    assert {"overload", "cooling_fault", "oil_leak", "oil_theft", "phase_unbalance", "through_fault", "sensor_stuck"} <= kinds
    assert set(cat["sensors"]) == {"OTI_C", "WTI_C", "OLI_pct"}


def test_stream_emits_ordered_frames_the_3d_view_can_read(c):
    ticks = _take(c, 3)
    assert len(ticks) == 3
    assert [t["tick"] for t in ticks] == sorted(t["tick"] for t in ticks)
    f = ticks[-1]["frame"]
    assert f["OTI_C"] and f["twin_oil_C"] and "T" in f["timestamp"]
    assert ticks[-1]["simulated"] is True


def test_inject_shows_up_and_clear_removes_it(c):
    r = c.post("/api/live/inject", json={"kind": "overload", "params": {"level_pu": 1.25}})
    assert r.status_code == 200 and r.json()["kind"] == "overload"
    assert [i["kind"] for i in _take(c, 2)[-1]["injections"]] == ["overload"]
    assert c.post("/api/live/clear", json={}).json()["removed"] == 1
    assert _take(c, 1)[0]["injections"] == []


def test_bad_inject_is_a_400(c):
    assert c.post("/api/live/inject", json={"kind": "nope"}).status_code == 400
    assert c.post("/api/live/inject", json={"kind": "overload", "params": {"level_pu": 9}}).status_code == 400


def test_control_sets_rate_and_pause(c):
    assert c.post("/api/live/control", json={"rate": 5}).json()["rate"] == 5
    assert c.post("/api/live/control", json={"paused": True}).json()["paused"] is True
    assert c.post("/api/live/control", json={"paused": False, "rate": 20}).json()["paused"] is False
    assert c.post("/api/live/control", json={"rate": 0}).status_code == 422
