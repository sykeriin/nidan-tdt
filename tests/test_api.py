"""dt/api.py facade: every function on every cached dataset; only DataFrames / contracts dataclasses come back."""
import itertools
from pathlib import Path

import pandas as pd
import pytest

from contracts.models import AnalysisResult, Dataset, Health, InspectResult, Run, StateAt
from dt import api

ROOT = Path(__file__).resolve().parent.parent
IDS = list(api.CACHED)


def test_list_datasets():
    df = api.list_datasets()
    assert isinstance(df, pd.DataFrame)
    assert set(IDS) <= set(df["dataset_id"]) and df.set_index("dataset_id").loc[IDS, "cached"].all()
    assert str(df["start"].dt.tz) == "Asia/Kolkata"


@pytest.mark.parametrize("dataset_id", IDS)
def test_get_run(dataset_id):
    r = api.get_run(dataset_id)
    assert isinstance(r, Run) and isinstance(r.analysis, AnalysisResult) and isinstance(r.analysis.health, Health)
    assert isinstance(r.trend, pd.DataFrame) and isinstance(r.health_series, pd.DataFrame)
    assert {"twin_oil_C", "residual_oil_C", "aging_rate_actual"} <= set(r.trend.columns)
    assert len(r.health_series) == len(r.trend) and r.health_series["score"].between(0, 100).all()
    assert r.summary["plausibility"]["OTI_C"] in ("plausible", "suspect", "not checked")
    assert (r.trend["simulated"] == (dataset_id != "kaggle")).all()


@pytest.mark.parametrize("dataset_id", IDS)
def test_state_at(dataset_id):
    r = api.get_run(dataset_id)
    t = r.trend["timestamp"].iloc[len(r.trend) // 2]
    s = api.state_at(dataset_id, t)
    assert isinstance(s, StateAt) and s.timestamp == t and isinstance(s.health, Health)
    assert "twin_oil_C" in s.twin and "OTI_C" in s.row and "twin_oil_C" not in s.row
    assert all(t - pd.Timedelta(hours=24) < a.timestamp <= t for a in s.alerts)
    assert s.health.score == pytest.approx(r.health_series["score"].iloc[len(r.trend) // 2])
    with pytest.raises(ValueError):
        api.state_at(dataset_id, r.trend["timestamp"].iloc[0] - pd.Timedelta(days=1))


@pytest.mark.parametrize("dataset_id", IDS)
def test_replay(dataset_id):
    waits = []
    states = list(itertools.islice(api.replay(dataset_id, speed=900, sleep=waits.append), 4))
    assert len(states) == 4 and all(isinstance(s, StateAt) for s in states)
    assert [s.timestamp for s in states] == list(api.get_run(dataset_id).trend["timestamp"].iloc[:4])
    assert all(w >= 0 for w in waits) and len(waits) == 3


@pytest.mark.parametrize("dataset_id", IDS)
def test_snapshot_table(dataset_id):
    t = api.snapshot_table(dataset_id)
    assert isinstance(t, pd.DataFrame) and len(t) > 0
    assert t["score"].is_monotonic_increasing and list(t["rank"]) == list(range(1, len(t) + 1))


@pytest.mark.parametrize("dataset_id", IDS)
def test_report_pdf_is_a_stub(dataset_id):
    with pytest.raises(NotImplementedError):
        api.report_pdf(dataset_id)


def test_unknown_dataset():
    with pytest.raises(KeyError):
        api.get_run("nope")


def test_self_test_cpri_format():
    t = api.self_test()
    assert list(t.columns) == ["section", "item", "unit", "setting", "reference", "software", "diff", "diff_pct", "pass"]
    assert set(t["section"]) == {"measurement", "current_trip", "temperature_trip", "software_trip_check"}
    assert len(t[t.section == "measurement"]) == 6 and t["pass"].all()
    trips = t[t.section == "software_trip_check"]
    assert (trips["software"] == trips["setting"]).all()           # our comparators trip at 50 A / 60 C


def test_inspect_and_load_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RUNS", tmp_path)                    # keep test uploads out of the real cache
    f = ROOT / "data" / "fixtures" / "F15r_organizer_records_no_time.xlsx"
    ir = api.inspect_file([f])
    assert isinstance(ir, InspectResult) and ir.proposals
    ds = api.load_file([f], name="F15r")
    assert isinstance(ds, Dataset) and ds.mode == "snapshot"
    did = ds.health_report["dataset_id"]
    assert did.startswith("u-") and did in set(api.list_datasets()["dataset_id"])
    r = api.get_run(did)
    assert r.mode == "snapshot" and r.analysis.alerts == [] and len(api.snapshot_table(did)) == 675
    with pytest.raises(ValueError):
        api.state_at(did, "2026-04-01")
