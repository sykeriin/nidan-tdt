"""Reporting layer: self-contained HTML, full CSV, JSON, over HTTP and for every kind of dataset."""
import io
import json
import re
import shutil
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from dt import api
from server import app as appmod

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def client():
    return TestClient(appmod.app)


def test_html_is_self_contained_and_says_what_it_is(client):
    r = client.get("/api/datasets/S2/report", params={"fmt": "html"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    assert not re.findall(r'(?:src|href)="https?://', html) and "<script" not in html           # nothing loaded from anywhere
    assert html.count("<svg") >= 3                                                              # charts are inline
    for must in ("SIMULATED", "Health Index", "Method, assumptions and limitations", "Chance of a temperature limit", "scenario S2"):
        assert must in html
    assert "not a failure forecast" in html and "not fitted" in html.lower()
    assert r.headers["content-disposition"].startswith("inline")


def test_real_data_is_not_labelled_simulated(client):
    html = client.get("/api/datasets/kaggle/report").text
    assert "SIMULATED: this report" not in html and "estimated from the data" in html


def test_numbers_in_the_report_come_from_the_run(client):
    run = api.get_run("S2")
    html = client.get("/api/datasets/S2/report").text
    assert f"{len(run.analysis.alerts)}" in html
    assert str(run.analysis.health.band) in html


def test_csv_has_every_sample_health_and_alert_flags_and_no_ground_truth(client):
    r = client.get("/api/datasets/S2/report", params={"fmt": "csv"})
    assert r.headers["content-disposition"].startswith("attachment")
    df = pd.read_csv(io.StringIO(r.text))
    run = api.get_run("S2")
    assert len(df) == len(run.trend) and {"health_score", "health_band", "alerts_active_24h", "alert_types"} <= set(df.columns)
    assert not any(c.startswith(("gt_", "alarm_")) for c in df.columns)
    assert df["alerts_active_24h"].max() >= 1 and "residual_drift" in ";".join(df["alert_types"].dropna().astype(str))


def test_json_is_valid_with_no_nan_and_carries_the_limitations(client):
    r = client.get("/api/datasets/S1/report", params={"fmt": "json"})
    assert "NaN" not in r.text
    j = json.loads(r.text)
    assert j["dataset"]["simulated"] is True and j["health"]["band"] and j["alerts"] and j["outlook_at_end"]["rul"]
    assert any("not a failure forecast" in x for x in j["limitations"])


def test_bad_format_and_unknown_dataset(client):
    assert client.get("/api/datasets/S2/report", params={"fmt": "pdf"}).status_code == 400
    assert client.get("/api/datasets/nope/report").status_code == 404


def test_snapshot_dataset_still_gets_a_report(client):
    ds = api.load_file([ROOT / "data" / "fixtures" / "F15r_organizer_records_no_time.xlsx"], name="records", dataset_id="u-reptest")
    try:
        assert ds.mode == "snapshot"
        r = client.get("/api/datasets/u-reptest/report")
        assert r.status_code == 200 and "no time series" in r.text.lower()
        assert client.get("/api/datasets/u-reptest/report", params={"fmt": "csv"}).status_code == 200
    finally:
        shutil.rmtree(appmod.ROOT / "data" / "cache" / "runs" / "u-reptest", ignore_errors=True)
