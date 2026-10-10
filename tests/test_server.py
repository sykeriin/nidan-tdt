"""FastAPI wrapper: every endpoint on every cached dataset, plus upload, errors, CORS, JSON format, static build."""
import importlib
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dt import api
from server import app as appmod

ROOT = Path(__file__).resolve().parent.parent
IDS = list(api.CACHED)
ISO = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?[+-]\d\d:\d\d$")


@pytest.fixture(scope="module")
def client():
    return TestClient(appmod.app)


def test_list_datasets(client):
    r = client.get("/api/datasets")
    assert r.status_code == 200
    rows = {d["dataset_id"]: d for d in r.json()}
    assert set(IDS) <= set(rows)
    assert ISO.match(rows["N"]["start"]) and rows["N"]["simulated"] is True and rows["kaggle"]["simulated"] is False


@pytest.mark.parametrize("dataset_id", IDS)
def test_run(client, dataset_id):
    r = client.get(f"/api/datasets/{dataset_id}/run")
    assert r.status_code == 200
    j = r.json()
    assert j["dataset_id"] == dataset_id and j["analysis"]["health"]["band"] in ("Green", "Yellow", "Red")
    assert {"OTI_C", "twin_oil_C", "residual_oil_C", "aging_rate_actual"} <= set(j["series"])
    assert all(len(s["t"]) == len(s["v"]) <= 2000 for s in j["series"].values())
    assert all(len(s["v"]) <= 2000 for s in j["health_series"].values())
    assert ISO.match(j["series"]["OTI_C"]["t"][0]) and ISO.match(j["start"])
    assert "NaN" not in r.text and "Infinity" not in r.text           # NaN -> null
    for a in j["analysis"]["alerts"][:5]:
        assert ISO.match(a["timestamp"]) and isinstance(a["simulated"], bool)


def test_run_downsampling_keeps_extremes(client):
    full = api.get_run("kaggle").trend
    j = client.get("/api/datasets/kaggle/run").json()
    assert j["downsampled"] is True and j["rows_in_range"] == len(full)
    oti = j["series"]["OTI_C"]["v"]
    assert len(oti) <= 2000 and max(oti) == pytest.approx(full["OTI_C"].max())   # the 250 C glitch survives
    small = client.get("/api/datasets/kaggle/run", params={"max_points": 100}).json()
    assert all(len(s["v"]) <= 100 for s in small["series"].values())


def test_run_time_range(client):
    j = client.get("/api/datasets/S2/run", params={"start": "2026-04-20T00:00:00+05:30", "end": "2026-04-22"}).json()
    assert j["rows_in_range"] == 2 * 96 + 1 and j["downsampled"] is False
    assert j["start"] == "2026-04-20T00:00:00+05:30" and j["end"] == "2026-04-22T00:00:00+05:30"


@pytest.mark.parametrize("dataset_id", IDS)
def test_state(client, dataset_id):
    t = api.get_run(dataset_id).trend["timestamp"].iloc[100].isoformat()
    r = client.get(f"/api/datasets/{dataset_id}/state", params={"t": t})
    assert r.status_code == 200
    j = r.json()
    assert j["timestamp"] == t and 0 <= j["health"]["score"] <= 100 and "twin_oil_C" in j["twin"]


@pytest.mark.parametrize("dataset_id", IDS)
def test_replay(client, dataset_id):
    r = client.get(f"/api/datasets/{dataset_id}/replay", params={"limit": 5})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(x) for x in r.text.splitlines()]
    assert len(lines) == 5 and all(ISO.match(x["timestamp"]) for x in lines)
    assert lines[0]["timestamp"] < lines[-1]["timestamp"]


@pytest.mark.parametrize("dataset_id", IDS)
def test_snapshot(client, dataset_id):
    j = client.get(f"/api/datasets/{dataset_id}/snapshot").json()
    assert "rank" in j["columns"] and j["rows"][0]["rank"] == 1


@pytest.mark.parametrize("dataset_id", IDS)
def test_report_not_built(client, dataset_id):
    r = client.get(f"/api/datasets/{dataset_id}/report.pdf")
    assert r.status_code == 501 and "not built" in r.json()["detail"]


def test_self_test(client):
    j = client.get("/api/self-test").json()
    assert j["columns"][:3] == ["section", "item", "unit"] and all(row["pass"] for row in j["rows"])


def test_readable_errors(client):
    assert client.get("/api/datasets/nope/run").status_code == 404
    r = client.get("/api/datasets/N/state", params={"t": "1999-01-01"})
    assert r.status_code == 400 and "before the first sample" in r.json()["detail"]
    r = client.get("/api/datasets/N/state", params={"t": "garbage"})
    assert r.status_code == 422 and r.json()["detail"].startswith("query.t")
    assert client.get("/api/datasets/N/run", params={"start": "2026-04-10", "end": "2026-04-01"}).status_code == 400
    assert client.get("/api/datasets/N/run", params={"max_points": 5000}).status_code == 422


def test_cors_for_local_dev(client):
    r = client.get("/api/datasets", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_upload_inspect_load_and_registry(client, tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(appmod, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(appmod, "REGISTRY", tmp_path / "uploads" / "registry.json")
    f3 = ROOT / "data" / "fixtures" / "F3_l1l2l3_fahrenheit_ddmm.csv"
    with open(f3, "rb") as fh:
        r = client.post("/api/inspect", files=[("files", (f3.name, fh, "text/csv"))])
    assert r.status_code == 200 and {p["canonical"] for p in r.json()["proposals"]} >= {"IR", "OTI_C"}
    with open(f3, "rb") as fh:
        r = client.post("/api/datasets", files=[("files", (f3.name, fh, "text/csv"))],
                        data={"name": "F3 upload", "asset": json.dumps({"rating_kVA": 1000, "lv_voltage_V": 415})})
    assert r.status_code == 201, r.text
    did = r.json()["dataset_id"]
    assert r.json()["mode"] == "full" and r.json()["capabilities"]["unbalance"] is True
    listed = {d["dataset_id"]: d for d in client.get("/api/datasets").json()}
    assert listed[did]["files"] == [f3.name] and listed[did]["name"] == "F3 upload"
    run = client.get(f"/api/datasets/{did}/run").json()
    assert run["analysis"]["health"]["score"] >= 0 and "twin_oil_C" in run["series"]
    f15r = ROOT / "data" / "fixtures" / "F15r_organizer_records_no_time.xlsx"
    with open(f15r, "rb") as fh:
        r = client.post("/api/datasets", files=[("files", (f15r.name, fh, "application/octet-stream"))])
    snap = r.json()["dataset_id"]
    assert r.json()["mode"] == "snapshot"
    assert client.get(f"/api/datasets/{snap}/run").json()["records"]["rows"][0]["rank"] == 1
    assert client.get(f"/api/datasets/{snap}/state", params={"t": "2026-04-01"}).status_code == 400


def test_upload_errors(client, tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "UPLOADS", tmp_path / "uploads")
    r = client.post("/api/datasets", files=[("files", ("x.pdf", b"%PDF", "application/pdf"))])
    assert r.status_code == 400 and "unsupported file type" in r.json()["detail"]
    r = client.post("/api/datasets", files=[("files", ("x.csv", b"a,b\n1,2\n", "text/csv"))], data={"mapping": "{bad"})
    assert r.status_code == 400 and "mapping must be JSON" in r.json()["detail"]
    assert client.post("/api/datasets").status_code == 422
    r = client.post("/api/datasets", files=[("files", ("bare.csv", b"Load_A,Amb_C\n1,2\n3,4\n", "text/csv"))])
    assert r.status_code == 400 and "no trend table" in r.json()["detail"]


def test_serves_react_build_from_same_app(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<!doctype html><title>DT</title>", encoding="utf-8")
    monkeypatch.setenv("DT_WEB_DIST", str(tmp_path))
    mod = importlib.reload(appmod)
    try:
        c = TestClient(mod.app)
        assert "<title>DT</title>" in c.get("/").text
        assert c.get("/api/datasets").status_code == 200        # API still wins over the static mount
    finally:
        monkeypatch.delenv("DT_WEB_DIST")
        importlib.reload(appmod)


def test_openapi_lists_every_facade_endpoint(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/api/datasets", "/api/inspect", "/api/datasets/{dataset_id}/run", "/api/datasets/{dataset_id}/state",
              "/api/datasets/{dataset_id}/replay", "/api/self-test", "/api/datasets/{dataset_id}/snapshot",
              "/api/datasets/{dataset_id}/report.pdf"):
        assert p in paths


def test_asset_form_field_never_opens_a_server_file(client, tmp_path):
    """A JSON string in `asset` used to be treated as a YAML path on the server."""
    f = ("data.csv", (ROOT / "data" / "fixtures" / "F1_canonical.csv").read_bytes(), "text/csv")
    for bad in ('"config/thresholds.yaml"', '"C:/Windows/win.ini"', "123", '{"rating_kVA": 500, "evil": 1}', '{"name": ["x"]}'):
        r = client.post("/api/datasets", files={"files": f}, data={"asset": bad})
        assert r.status_code == 400, (bad, r.text)
        assert "asset" in r.json()["detail"]
    ok = client.post("/api/datasets", files={"files": f}, data={"asset": '{"rating_kVA": 500, "lv_voltage_V": 415}'})
    assert ok.status_code == 201
    import shutil
    shutil.rmtree(appmod.ROOT / "data" / "cache" / "runs" / ok.json()["dataset_id"], ignore_errors=True)
    shutil.rmtree(appmod.UPLOADS / ok.json()["dataset_id"], ignore_errors=True)


@pytest.mark.parametrize("dataset_id", IDS)
def test_thermal_profile_and_components(client, dataset_id):
    t = api.get_run(dataset_id).trend["timestamp"].iloc[100].isoformat()
    j = client.get(f"/api/datasets/{dataset_id}/thermal-profile", params={"t": t}).json()
    assert {"bottom_oil_C", "top_oil_C", "hot_spot_C", "heat_dissipated_W", "oil_flow_intensity"} <= set(j["values"])
    assert j["values"]["bottom_oil_C"]["estimated"] is True and j["params"]["tau_oil_min"] == 180
    c = client.get(f"/api/datasets/{dataset_id}/components", params={"t": t}).json()
    assert "winding-Y" in c["parts"] and c["parts"]["oil"]["equations"][0]["symbolic"].startswith("θo,ss")
    assert client.get(f"/api/datasets/{dataset_id}/components", params={"t": "1990-01-01T00:00"}).status_code == 400


def test_whatif_and_findings(client):
    j = client.get("/api/whatif", params={"load_pu": 1.1, "ambient_C": 40, "cooling": 0.8}).json()
    assert j["hot_spot_C"] > j["top_oil_C"] > 40 and len(j["curve"]["t_min"]) == len(j["curve"]["top_oil_C"])
    assert j["start"]["from"] == "cold (ambient)"
    assert client.get("/api/whatif", params={"load_pu": 5, "ambient_C": 40}).status_code == 422
    f = client.get("/api/datasets/S5/findings").json()
    assert f["stress"]["triggered"] and any(g["cause"] == "Short circuit" for g in f["findings"])
    assert "class" in f["stress"]["last_event"]


@pytest.mark.parametrize("dataset_id", IDS)
def test_frames(client, dataset_id):
    full = api.get_run(dataset_id).trend
    j = client.get(f"/api/datasets/{dataset_id}/frames", params={"fields": "OTI_C,twin_oil_C,health_score,health_band"}).json()
    assert j["rows"] == len(full) == len(j["timestamp"])                      # every sample, not downsampled
    assert set(j["columns"]) == {"OTI_C", "twin_oil_C", "health_score", "health_band"}
    assert all(len(v) == j["rows"] for v in j["columns"].values())
    assert ISO.match(j["timestamp"][0])
    part = client.get(f"/api/datasets/{dataset_id}/frames",
                      params={"fields": "OTI_C", "start": j["timestamp"][10], "end": j["timestamp"][19], "every": 3}).json()
    assert part["rows"] == 4 and part["timestamp"][0] == j["timestamp"][10]
    assert client.get(f"/api/datasets/{dataset_id}/frames", params={"fields": "nope"}).status_code == 400


def test_companion_responses_cover_every_alert_type(client):
    from analytics.common import ALERT_MODULES
    j = client.get("/api/companion/responses").json()
    assert set(j["types"]) == set(ALERT_MODULES)
    assert {"info", "warning", "critical"} <= set(j["severity_label"])


def test_dashboard_test_alert_reaches_a_listening_companion(client):
    first = client.get("/api/companion/test-alerts").json()          # a new client learns the latest seq, gets nothing
    assert first["items"] == []
    r = client.post("/api/companion/test-alert", json={"type": "loading_high", "severity": "critical"})
    assert r.status_code == 200, r.text
    j = client.get("/api/companion/test-alerts", params={"since": first["latest"]}).json()
    assert [t["alert"]["type"] for t in j["items"]] == ["loading_high"]
    a = j["items"][0]["alert"]
    assert a["severity"] == "critical" and a["origin"] == "asset" and a["id"].startswith("test-") and a["timestamp"]
    assert client.get("/api/companion/test-alerts", params={"since": j["latest"]}).json()["items"] == []   # delivered once
    sensor = client.post("/api/companion/test-alert", json={"type": "stuck_sensor", "severity": "warning"}).json()["alert"]
    assert sensor["origin"] == "sensor"
    assert client.post("/api/companion/test-alert", json={"type": "nope", "severity": "info"}).status_code == 400
