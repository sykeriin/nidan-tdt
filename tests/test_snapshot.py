"""Snapshot (records) mode: per-test records without time, as in the CPRI screening workbook (fixture F15r)."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from contracts.canonical import validate
from ingest.adapter import load
from twin import thermal
from twin.engine import TwinEngine

ROOT = Path(__file__).resolve().parent.parent
F15R = ROOT / "data" / "fixtures" / "F15r_organizer_records_no_time.xlsx"


@pytest.fixture(scope="module")
def ds():
    return load([F15R], simulated=True)


@pytest.fixture(scope="module")
def twin(ds):
    return TwinEngine().run(ds)


def test_snapshot_mode_and_contract(ds):
    t = ds.trend
    assert ds.mode == "snapshot"
    assert "timestamp" not in t and t["record_id"].is_unique and len(t) == 675
    assert validate(t) == []
    assert t["record_id"].iloc[0] == "REC-0001"
    assert "gt_validity_label" in t and "extra_sensor_s1" in t


def test_time_features_disabled_with_message(ds):
    for f in ("ageing_rul", "residual_fidelity", "lead_time_eval", "replay"):
        assert ds.capabilities[f] is False
        assert ds.health_report["disabled"][f]
    assert ds.capabilities["thermal_twin"] and ds.capabilities["residual"]
    assert any("Snapshot mode" in w for w in ds.health_report["warnings"])


def test_per_record_capability_matrix(ds):
    per = ds.health_report["record_capabilities"]
    assert len(per) == len(ds.trend) and per["thermal_twin"].all()
    assert (~per["residual"]).sum() == ds.trend["OTI_C"].isna().sum()        # blank OTI cells -> no residual there
    assert not per["unbalance"].any()                                         # single current


def test_duplicate_pairs_flagged_and_kept(ds):
    assert ds.trend["dq_flags"].str.contains("DUP_IDENT").sum() == 6          # 3 pairs, both records kept


def test_steady_state_twin_matches_library(ds, twin):
    e = TwinEngine()
    r = twin.iloc[10]
    idx = pd.date_range("2026-01-01", periods=96 * 4, freq="15min")
    oil, hs = thermal.run_segment(e.tr, pd.Series(idx), np.full(len(idx), r["I_mean"]), np.full(len(idx), r["amb_C"]))
    assert r["twin_oil_C"] == pytest.approx(oil[-1], abs=1e-6)               # long constant run converges to it
    assert r["twin_hs_C"] == pytest.approx(hs[-1], abs=1e-6)


def test_snapshot_outputs(twin):
    assert twin.attrs["mode"] == "snapshot" and twin.attrs["rul"] is None
    assert {"twin_oil_C", "twin_hs_C", "residual_oil_C", "aging_rate_point", "implausible_rise"} <= set(twin.columns)
    assert "days_aged_cum" not in twin and "fidelity_rmse_C" not in twin
    assert twin.attrs["plausibility"]["OTI_C"] == "plausible"
    assert twin["residual_oil_C"].notna().sum() == 667


def test_snapshot_catches_bad_oti(ds):
    bad = ds.trend.copy()
    bad["OTI_C"] = bad["amb_C"] + 2.0
    assert TwinEngine().run(bad).attrs["plausibility"]["OTI_C"] == "suspect"


def test_records_without_oti_are_not_checked(ds):
    r = TwinEngine().run(ds.trend.drop(columns=["OTI_C"]))
    assert r["twin_oil_C"].notna().all() and r["residual_oil_C"].isna().all()
    assert r.attrs["plausibility"]["OTI_C"] == "not checked"


def test_interval_assigns_assumed_time(ds):
    d = load([F15R], simulated=True, interval="15min", assumed_start="2026-04-01 00:00")
    assert d.mode == "full"
    assert d.trend["timestamp"].iloc[0] == pd.Timestamp("2026-04-01 00:00", tz="Asia/Kolkata")
    assert (d.trend["timestamp"].diff().dropna() == pd.Timedelta("15min")).all()
    assert d.trend["dq_flags"].str.contains("ASSUMED_TIME").all()
    r = TwinEngine().run(d)
    assert r["twin_oil_C"].notna().all() and r.attrs["mode"] == "full"


def test_no_time_and_no_id_still_errors(tmp_path):
    f = tmp_path / "bare.csv"
    pd.DataFrame({"Load_Current_A": [50.0, 60.0], "Ambient_Temperature_C": [30.0, 31.0]}).to_csv(f, index=False)
    with pytest.raises(ValueError, match="no trend table found"):
        load([f])
