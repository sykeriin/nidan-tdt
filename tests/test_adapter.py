"""Tier 1 adapter: six fixtures, one code path, correct mode and capabilities (DATA_INGESTION_SPEC.md §5)."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from contracts.canonical import validate
from ingest import map as cmap
from ingest.adapter import inspect, load, map_row
from ingest.units import header_hint

ROOT = Path(__file__).resolve().parent.parent
FX = ROOT / "data" / "fixtures"
KAGGLE = sorted((ROOT / "data" / "raw" / "kaggle").glob("*.csv"))

FIXTURES = {
    "F1": ([FX / "F1_canonical.csv"], "full", {"unbalance": True, "voltage_quality": True, "lead_time_eval": True}),
    "F2": (KAGGLE, "full", {"unbalance": True, "wti_check": False, "oil_leak_theft": True, "neutral_measured": True}),
    "F3": ([FX / "F3_l1l2l3_fahrenheit_ddmm.csv"], "full", {"unbalance": True, "voltage_quality": True}),
    "F4": ([FX / "F4_excel_trend_events.xlsx"], "full", {"through_fault": True, "unbalance": True}),
    "F8": ([FX / "F8_kva_only.csv"], "meter_only",
           {"thermal_twin": True, "residual_fidelity": False, "unbalance": False, "voltage_quality": False}),
    "F6": ([FX / "F6_line_line_kA.csv"], "full", {"voltage_quality": True, "unbalance": True}),
    "F15": ([FX / "F15_organizer_style.xlsx"], "full",
            {"unbalance": False, "voltage_quality": False, "lead_time_eval": True, "residual_fidelity": True}),
}


@pytest.fixture(scope="module")
def loaded():
    out = {}
    for k, (paths, _, _) in FIXTURES.items():
        out[k] = load(paths, asset=None if k == "F2" else "config/asset.yaml", simulated=k != "F2")
    return out


@pytest.fixture(scope="module")
def truth():
    n = pd.read_csv(ROOT / "data" / "generated" / "trend_N.csv", parse_dates=["timestamp"])
    s5 = pd.read_csv(ROOT / "data" / "generated" / "trend_S5.csv", parse_dates=["timestamp"])
    return pd.concat([n, s5[s5["timestamp"] >= "2026-04-24"]]).drop_duplicates("timestamp")


@pytest.mark.parametrize("fid", list(FIXTURES))
def test_mode_capabilities_contract(loaded, fid):
    ds = loaded[fid]
    _, mode, caps = FIXTURES[fid]
    assert ds.mode == mode
    for cap, want in caps.items():
        assert ds.capabilities[cap] is want, cap
    assert validate(ds.trend, ds.events) == []
    assert ds.trend["amb_C"].notna().all()


@pytest.mark.parametrize("fid", ["F1", "F3", "F4", "F8", "F6", "F15"])
def test_amps_match_truth_within_1pct(loaded, truth, fid):
    m = loaded[fid].trend.merge(truth[["timestamp", "I_mean"]], on="timestamp", suffixes=("", "_true"))
    assert len(m) == len(loaded[fid].trend)
    assert ((m["I_mean"] - m["I_mean_true"]).abs() / m["I_mean_true"]).max() < 0.01


def test_f3_fahrenheit_and_day_first(loaded, truth):
    t = loaded["F3"].trend
    assert t["timestamp"].iloc[0] == pd.Timestamp("2026-04-01 00:00", tz="Asia/Kolkata")  # not 4 Jan
    m = t.merge(truth[["timestamp", "OTI_C"]], on="timestamp", suffixes=("", "_true"))
    assert (m["OTI_C"] - m["OTI_C_true"]).abs().max() < 0.1


def test_f4_excel_events(loaded):
    ev = loaded["F4"].events
    assert len(ev) == 3 and (ev["event_type"] == "through_fault").all()
    np.testing.assert_allclose(ev["peak_pu"], [6.0, 10.0, 3.5], rtol=0.01)
    assert loaded["F4"].trend["timestamp"].min().day == 24


def test_f8_meter_only_derives_amps_and_fills_ambient(loaded):
    t = loaded["F8"].trend
    assert t["dq_flags"].str.contains("DERIVED_IR").all()
    assert t["dq_flags"].str.contains("IMPUTED_AMB").all()
    assert "OTI_C" not in t


def test_f6_kA_and_line_line(loaded, truth):
    t = loaded["F6"].trend
    m = t.merge(truth[["timestamp", "VR", "IR"]], on="timestamp", suffixes=("", "_true"))
    np.testing.assert_allclose(m["VR"], m["VR_true"], rtol=0.005)
    np.testing.assert_allclose(m["IR"], m["IR_true"], rtol=0.005)
    assert t["dq_flags"].str.contains("DERIVED_VR").all()


def test_f2_kaggle_auto_map(loaded):
    ds = loaded["F2"]
    assert "WTI_C" not in ds.trend                       # 0/1 column rejected as a temperature
    assert {"alarm_mog_a", "alarm_oti_a", "alarm_oti_t"} <= set(ds.trend.columns)
    assert ds.asset["nameplate_source"] == "estimated"


def test_map_row_matches_batch(loaded):
    ds = loaded["F3"]
    schema = {"columns": cmap.schema_from_proposals(
        [{**m, "canonical": m["canonical"]} for m in ds.health_report["mapping"]])}
    raw = pd.read_csv(FIXTURES["F3"][0][0]).iloc[40].to_dict()
    row = map_row(raw, schema, "config/asset.yaml")
    b = ds.trend.iloc[40]
    assert row["I_mean"] == pytest.approx(b["I_mean"])
    assert row["OTI_C"] == pytest.approx(b["OTI_C"])
    assert row["loading_pct"] == pytest.approx(b["loading_pct"])


def test_inspect_proposes_without_loading():
    r = inspect(FIXTURES["F3"][0])
    got = {p["source"]: p["canonical"] for p in r.proposals}
    assert got["L1 Current (A)"] == "IR" and got["Oil Temp (°F)"] == "OTI_C"
    assert len(r.preview) == 10


def test_phase_scheme_ib_ambiguity():
    abc = pd.DataFrame({"ia": [1.0, 2], "ib": [1.0, 2], "ic": [1.0, 2]})
    ryb = pd.DataFrame({"ir": [1.0, 2], "iy": [1.0, 2], "ib": [1.0, 2]})
    assert {p["source"]: p["canonical"] for p in cmap.propose(abc)}["ib"] == "IY"
    assert {p["source"]: p["canonical"] for p in cmap.propose(ryb)}["ib"] == "IB"


def test_unit_hints():
    assert header_hint("Oil Temp (°F)") == "F"
    assert header_hint("I_R [kA]") == "kA"
    assert header_hint("Top Oil Temp") is None


def test_adapter_offline(no_network):
    ds = load(FIXTURES["F8"][0])
    assert ds.mode == "meter_only" and ds.trend["amb_C"].notna().all()


def test_f15_organizer_naming(loaded, truth):
    """CPRI screening-workbook style: Title_Case_unit headers, anonymous sensors, labels, dupes, blanks."""
    ds = loaded["F15"]
    m = {x["source"]: x["canonical"] for x in ds.health_report["mapping"]}
    assert m["Load_Current_A"] == "I_total" and m["Applied_Voltage_kV"] == "VRY"
    assert m["Ambient_Temperature_C"] == "ATI_C" and m["Oil_Temperature_C"] == "OTI_C"
    assert m["Validity_Label"] == "gt_validity_label"                       # hidden output -> quarantined
    t = ds.trend
    assert {"extra_sensor_s1", "extra_sensor_s2", "extra_sensor_s3", "extra_sensor_s4"} <= set(t.columns)
    assert t["dq_flags"].str.contains("DUP_IDENT").sum() == 3                # duplicate measurement pairs
    assert t["timestamp"].iloc[0] == pd.Timestamp("2026-04-01 00:00", tz="Asia/Kolkata")  # DD-MM-YYYY
    tr = truth[["timestamp", "VR", "VY", "VB"]].rename(columns={"VR": "VR_t", "VY": "VY_t", "VB": "VB_t"})
    mm = t[["timestamp", "VR"]].merge(tr, on="timestamp")
    np.testing.assert_allclose(mm["VR"], mm[["VR_t", "VY_t", "VB_t"]].mean(axis=1), rtol=0.005)  # kV L-L -> V L-N


def test_unit_suffix_does_not_break_alarm_or_phase_names():
    df = pd.DataFrame({"OTI_A": [0.0, 1], "MOG_A": [0.0, 1], "I_C": [10.0, 11], "I_A": [10.0, 11], "I_B": [10.0, 11]})
    got = {p["source"]: p["canonical"] for p in cmap.propose(df)}
    assert got["OTI_A"] == "alarm_oti_a" and got["MOG_A"] == "alarm_mog_a"
    assert got["I_C"] == "IB" and got["I_A"] == "IR" and got["I_B"] == "IY"


def test_hv_voltage_set_aside(tmp_path):
    f = tmp_path / "hv.csv"
    ts = pd.date_range("2026-04-01", periods=96, freq="15min")
    pd.DataFrame({"Timestamp": ts.strftime("%Y-%m-%d %H:%M"), "Applied_Voltage_kV": 11.0,
                  "Load_Current_A": 600.0, "Ambient_Temperature_C": 30.0}).to_csv(f, index=False)
    ds = load([f])
    assert "VR" not in ds.trend and "extra_vry_hv" in ds.trend
    assert any("HV-side" in d for d in ds.health_report["derived"])
    assert ds.trend["I_mean"].iloc[0] == pytest.approx(600)


def test_records_without_timestamp_get_clear_error(tmp_path):
    f = tmp_path / "records.csv"
    pd.DataFrame({"Test_ID": ["TRN-0001", "TRN-0002"], "Load_Current_A": [50.0, 60.0]}).to_csv(f, index=False)
    with pytest.raises(ValueError, match="per-test records keyed by 'Test_ID'"):
        load([f])
