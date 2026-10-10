"""Live ingestion: readings posted by a device become a dataset every dashboard page can use."""
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from dt import api
from server import app as appmod

COLS = ("IR", "IY", "IB", "VR", "VY", "VB", "OTI_C", "amb_C", "OLI_pct", "PF", "freq_Hz")


@pytest.fixture(scope="module")
def client():
    return TestClient(appmod.app)


def _rows(start_day=0, n=96):
    t = api.get_run("N").trend.iloc[start_day * 96: start_day * 96 + n]
    return [{**{c: float(r[c]) for c in COLS if pd.notna(r[c])}, "timestamp": r["timestamp"].isoformat()} for r in t.to_dict("records")]


@pytest.fixture
def session(client):
    name = "pytest-gw"
    yield name
    client.delete(f"/api/ingest/{name}")


def test_posted_readings_become_a_live_dataset(client, session):
    r = client.post("/api/ingest", json={"session": session, "rows": _rows(0)})
    assert r.status_code == 201 and r.json()["dataset_id"] == f"u-live-{session}" and r.json()["rows_total"] == 96 and r.json()["mode"] == "full"
    r2 = client.post("/api/ingest", json={"session": session, "rows": _rows(1)})
    assert r2.json()["rows_total"] == 192 and r2.json()["last_timestamp"] > r.json()["last_timestamp"]
    ids = {d["dataset_id"]: d for d in client.get("/api/datasets").json()}
    assert ids[f"u-live-{session}"]["simulated"] is False                       # a device's readings are not labelled simulated
    run = client.get(f"/api/datasets/u-live-{session}/run").json()
    assert run["name"] == f"Live feed: {session}" and len(run["series"]["OTI_C"]["t"]) == 192
    assert client.get(f"/api/datasets/u-live-{session}/brief", params={"t": run["end"]}).status_code == 200


def test_reposting_the_same_readings_does_not_duplicate_them(client, session):
    client.post("/api/ingest", json={"session": session, "rows": _rows(0)})
    r = client.post("/api/ingest", json={"session": session, "rows": _rows(0)})
    assert r.json()["rows_total"] == 96


def test_a_transformer_profile_can_be_attached(client, session):
    r = client.post("/api/ingest", json={"session": session, "rows": _rows(0), "asset": {"rating_kVA": 630, "lv_voltage_V": 415}})
    assert r.status_code == 201
    assert client.get(f"/api/datasets/u-live-{session}/run").json()["asset"]["rating_kVA"] == 630


@pytest.mark.parametrize("body, text", [
    ({"session": "bad name!", "rows": [{"a": 1}]}, "session"),
    ({"session": "ok", "rows": []}, "at least one"),
    ({"session": "ok", "rows": [{"foo": 1, "bar": 2}]}, "could not be read"),
])
def test_bad_ingest_is_refused_with_a_reason(client, body, text):
    r = client.post("/api/ingest", json=body)
    assert r.status_code == 400 and text in r.json()["detail"]
    assert "u-live-ok" not in {d["dataset_id"] for d in client.get("/api/datasets").json()}


def test_ending_a_session_removes_it(client):
    client.post("/api/ingest", json={"session": "pytest-end", "rows": _rows(0)})
    assert client.delete("/api/ingest/pytest-end").json() == {"ended": True}
    assert client.delete("/api/ingest/pytest-end").json() == {"ended": False}
    assert client.get("/api/datasets/u-live-pytest-end/run").status_code == 404


@pytest.mark.parametrize("bad", ["a b", "x" * 41, "a.b", "%2e%2e"])
def test_deleting_a_session_validates_the_name_first(client, bad):
    """The session name reaches the file system on delete, so it is checked exactly like on ingest."""
    assert client.delete(f"/api/ingest/{bad}").status_code == 400
    assert (appmod.ROOT / "data" / "cache" / "runs" / "N" / "run.json").exists()      # nothing outside a live session was touched


def test_end_live_rejects_traversal_names_directly():
    """HTTP clients normalise "/.." before it reaches the route, so the function itself must refuse such names too."""
    for bad in ("..", "../N", "a/b", "a\b", ""):
        with pytest.raises(ValueError):
            api.end_live(bad)
    assert (appmod.ROOT / "data" / "cache" / "runs" / "N" / "run.json").exists()
