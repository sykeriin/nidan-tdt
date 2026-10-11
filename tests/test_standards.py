"""India-profile condition detectors, the live condition board, the live source, the PDF report and the blueprint kit."""
import io
import json
import warnings
import zipfile

import pytest
from fastapi.testclient import TestClient

from server.app import app
from sim.live import LiveSession
from twin import condition

warnings.simplefilter("ignore")

CASES = [
    ("insulation_turn", {}, "turn_fault"),
    ("insulation_tank", {}, "earth_leakage"),
    ("moisture_ingress", {"ppm_per_day": 20}, "moisture_high"),
    ("charging_current", {}, "charging_current"),
    ("short_circuit", {}, "short_circuit_trip"),
]


@pytest.mark.parametrize("kind,params,alert", CASES)
def test_new_fault_raises_its_alert_and_a_clean_plant_does_not(kind, params, alert):
    s = LiveSession(seed=0)
    clean = {a.type for a in s.tick()["alerts"]}
    assert alert not in clean
    s.inject(kind, **params)
    seen = set()
    for _ in range(150):
        seen |= {a.type for a in s.tick()["alerts"]}
    assert alert in seen, f"{kind} should raise {alert}, got {sorted(seen)}"


def test_condition_board_covers_the_checklist_with_limits():
    s = LiveSession(seed=0)
    t = s.tick()
    from analytics.common import load_thresholds
    items = condition.board(t["frame"], load_thresholds(asset=s.asset), s.params(), s.asset, s.events)
    ids = {i["id"] for i in items}
    assert {"short_circuit", "overload", "thermal_capacity", "hot_spot", "turn_fault", "tank_insulation", "charging_current", "temp_alarm",
            "thermal_lag", "voltage", "life", "silica_gel", "moisture", "efficiency"} <= ids
    assert all(i["status"] in ("ok", "watch", "alarm", "na") and i["limit"] for i in items)
    assert {i["status"] for i in items} == {"ok"}          # a healthy plant is all green
    assert condition.silica(10)["label"].startswith("Blue") and condition.silica(90)["label"].startswith("Pink")


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        client.post("/api/live/control", json={"rate": 20, "paused": False})
        client.post("/api/live/session", json={"seed": 0})
        client.get("/api/live/stream?limit=5")
        yield client


def test_live_source_works_with_every_dashboard_call(c):
    j = c.post("/api/live/sync").json()
    assert j["dataset_id"] == "live" and j["rows"] > 100 and j["simulated"] is True
    iso = j["last_timestamp"]
    assert c.get("/api/datasets/live/run").status_code == 200
    assert c.get("/api/datasets/live/frames").json()["rows"] == j["rows"]
    assert c.get("/api/datasets/live/findings", params={"t": iso}).status_code == 200
    assert c.get("/api/datasets/live/components", params={"t": iso}).status_code == 200
    assert "live" not in [d["dataset_id"] for d in c.get("/api/datasets").json()]       # a source, not a dataset


def test_condition_endpoint_and_service(c):
    j = c.get("/api/live/condition").json()
    assert len(j["items"]) >= 14 and "IS 2026" in j["standard"]
    assert c.post("/api/live/service", json={"action": "dry_oil"}).status_code == 200
    assert c.post("/api/live/service", json={"action": "nope"}).status_code == 400


def test_pdf_report_has_the_snapshot_and_rejects_non_png(c):
    import base64
    c.post("/api/live/sync")
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    r = c.post("/api/datasets/live/report.pdf", json={"snapshot": "data:image/png;base64," + base64.b64encode(png).decode()})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert b"/Image" in r.content                                    # the snapshot is embedded
    assert c.post("/api/datasets/live/report.pdf", json={"snapshot": "data:image/png;base64,AAAA"}).status_code == 400


def test_blueprint_kit_is_complete(c):
    r = c.get("/api/blueprint.zip")
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"README_INSTALL.md", "transformer_blueprint.pdf", "drawings/DT-001_system_architecture.svg", "drawings/DT-005_general_arrangement.svg", "sensor_schedule.csv",
            "terminal_schedule.csv", "asset.yaml", "thresholds_india.yaml", "gateway/send_readings.py"} <= names
    assert z.read("transformer_blueprint.pdf")[:4] == b"%PDF"
    assert b"2U" in z.read("terminal_schedule.csv") and b"OTI_C" in z.read("sensor_schedule.csv")
    compile(z.read("gateway/send_readings.py"), "send_readings.py", "exec")
    assert c.get("/api/blueprint.pdf").content[:4] == b"%PDF"


def test_clients_share_one_session_and_phone_gets_alerts_without_a_tablet(c):
    """Two streams can run at once, and a live alert is queued for the phone from the ticker, not from a stream."""
    c.post("/api/live/clear")
    base = c.get("/api/companion/test-alerts").json()["latest"]
    c.post("/api/live/inject", json={"kind": "moisture_ingress", "params": {"ppm_per_day": 20}})
    a = [json.loads(x) for x in c.get("/api/live/stream?limit=60").text.splitlines() if x]
    b = [json.loads(x) for x in c.get("/api/live/stream?limit=3").text.splitlines() if x]
    assert len(a) == 60 and len(b) == 3
    items = c.get("/api/companion/test-alerts", params={"since": base}).json()["items"]
    assert any(i["alert"]["type"] in ("moisture_high", "silica_gel_exhausted") for i in items)
    assert all(i["alert"].get("live") is True for i in items)


def test_pdf_report_without_a_browser_snapshot_still_has_a_picture(c):
    c.post("/api/live/sync")
    r = c.post("/api/datasets/live/report.pdf")
    assert r.status_code == 200 and b"/Image" in r.content
