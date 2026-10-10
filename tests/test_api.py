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


@pytest.mark.parametrize("dataset_id", IDS)
def test_thermal_profile(dataset_id):
    r = api.get_run(dataset_id)
    t = r.trend["timestamp"].iloc[len(r.trend) // 2]
    tp = api.thermal_profile(dataset_id, t)
    v = {k: d["value"] for k, d in tp["values"].items()}
    row = r.trend.iloc[len(r.trend) // 2]
    assert v["top_oil_C"] == pytest.approx(row["twin_oil_C"]) and v["hot_spot_C"] == pytest.approx(row["twin_hs_C"])
    p = tp["params"]
    assert v["losses_total_W"] == pytest.approx(p["P0_W"] + p["Pk_W"] * row["load_pu"] ** 2)
    assert v["heat_stored_W"] == pytest.approx(v["losses_total_W"] - v["heat_dissipated_W"])
    assert v["ambient_C"] <= v["bottom_oil_C"] <= v["top_oil_C"] <= v["hot_spot_C"]
    assert 0 <= v["oil_flow_intensity"] <= 1
    assert v["tau_oil_min"] == 180 and v["tau_winding_min"] == 4
    assert all(tp["values"][k]["estimated"] for k in ("bottom_oil_C", "oil_flow_intensity", "radiator_effectiveness"))
    if r.mode == "meter_only":
        assert v["top_oil_measured_C"] is None and v["hot_spot_measured_C"] is None


def test_thermal_profile_steady_state_holds():
    """At constant load and ambient the twin settles on the profile's steady-state values, and stored heat -> 0."""
    from twin import thermal_profile as profile
    from twin.engine import TwinEngine
    eng = TwinEngine()
    ts = pd.date_range("2026-04-01", periods=3 * 96, freq="15min", tz="Asia/Kolkata")
    trend = pd.DataFrame({"timestamp": ts, "I_mean": 0.8 * eng.i_rated, "amb_C": 30.0})
    res = eng.run(trend)
    pr = profile.compute(res, eng.asset, 0.5).iloc[-1]
    assert res["twin_oil_C"].iloc[-1] == pytest.approx(pr["top_oil_ss_C"], abs=0.05)
    assert res["twin_hs_C"].iloc[-1] == pytest.approx(pr["hot_spot_ss_C"], abs=0.05)
    assert abs(pr["heat_stored_W"]) < 5


def test_radiator_effectiveness_tracks_cooling_fault():
    n = api.frames("N", fields=["radiator_effectiveness"])["radiator_effectiveness"].median()
    s2 = api.frames("S2", fields=["timestamp", "radiator_effectiveness"])
    late = s2[s2["timestamp"] >= s2["timestamp"].iloc[-1] - pd.Timedelta(days=3)]["radiator_effectiveness"].median()
    assert n == pytest.approx(1.0, abs=0.08)        # healthy plant ~ nominal twin
    assert late < n - 0.12                           # S2 cooling fault shows as lost radiator capacity


@pytest.mark.parametrize("dataset_id", IDS)
def test_components(dataset_id):
    from dt.components import PART_IDS
    r = api.get_run(dataset_id)
    t = r.trend["timestamp"].iloc[-1]
    c = api.components(dataset_id, t)
    assert set(c["parts"]) == set(PART_IDS)
    w = c["parts"]["winding-R"]
    age = next(e for e in w["equations"] if e["symbolic"] == "V = 2^((θh − 98)/6)")
    th = age["terms"][0]["value"]
    if th is not None:
        assert age["result"]["value"] == pytest.approx(2 ** ((th - 98) / 6), rel=1e-6)
        assert age["substituted"].startswith(f"V = 2^(({th:.1f} − 98)/6)")
    for part in c["parts"].values():
        for e in part["equations"]:
            assert (e["substituted"] is None) == (e["result"]["value"] is None)
    if r.mode == "meter_only":
        assert c["parts"]["oti"]["verdict"] is None


def test_components_findings_on_parts():
    c = api.components("S2", "2026-04-27T15:00")
    assert any(a["type"] == "hot_spot_high" for a in c["parts"]["winding-B"]["alerts"])
    assert c["parts"]["winding-B"]["tests"]
    assert c["parts"]["oti"]["verdict"] == "above"      # hotter than physics, but the channel is plausible overall
    k = api.components("kaggle", "2019-08-16T13:00")
    assert k["parts"]["oti"]["verdict"] == "suspect"
    assert any(a["id"].endswith("-OTI_C") for a in k["parts"]["oti"]["alerts"])


def test_whatif_matches_twin_steady_state():
    """At cooling 1 the what-if steady state equals the twin's own steady state (profile columns)."""
    from twin import thermal_profile as profile
    from twin.engine import TwinEngine
    eng = TwinEngine()
    ts = pd.date_range("2026-04-01", periods=3 * 96, freq="15min", tz="Asia/Kolkata")
    res = eng.run(pd.DataFrame({"timestamp": ts, "I_mean": 0.9 * eng.i_rated, "amb_C": 33.0}))
    w = api.whatif(0.9, 33.0, 1.0)
    assert w["top_oil_C"] == pytest.approx(res["twin_oil_C"].iloc[-1], abs=0.05)
    assert w["hot_spot_C"] == pytest.approx(res["twin_hs_C"].iloc[-1], abs=0.05)
    assert w["ageing_rate"] == pytest.approx(2 ** ((w["hot_spot_C"] - 98) / 6), rel=1e-3)
    assert w["heat_stored_W"] == 0 and w["heat_dissipated_W"] == w["losses_total_W"]


def test_whatif_cooling_and_start():
    good, weak = api.whatif(0.8, 30, 1.0), api.whatif(0.8, 30, 0.6)
    assert weak["top_oil_C"] > good["top_oil_C"] and weak["winding_gradient_K"] == good["winding_gradient_K"]
    assert weak["ageing_rate"] > weak["ageing_rate_nominal_cooling"] == pytest.approx(good["ageing_rate"])
    c = good["curve"]
    assert c["top_oil_C"][0] == pytest.approx(30) and abs(c["top_oil_C"][-1] - good["top_oil_C"]) < 1.0
    w = api.whatif(0.74, 36.4, 1.0, "S2", "2026-04-27T15:00")
    assert w["start"]["from"] == "twin state" and 0 < w["time_to_steady_min"] < 4 * 180
    with pytest.raises(ValueError):
        api.whatif(0.8, 30, 0.0)


def test_whatif_day_agrees_with_steady_and_scores_health():
    """The what-if day ends where the steady answer says (any cooling), carries health columns, and raises nothing
    at a healthy operating point (no sensor artefacts from the simulated meter)."""
    t = "2026-04-16T12:00"
    for load, amb, cool in ((0.62, 35, 1.0), (1.0, 35, 0.6)):
        s, d = api.whatif(load, amb, cool, "S2", t), api.whatif_day("S2", t, load, amb, cool)
        end = d["frames"].iloc[-1]
        assert end["twin_oil_C"] == pytest.approx(s["top_oil_C"], abs=1.0)
        assert end["twin_hs_C"] == pytest.approx(s["hot_spot_C"], abs=1.0)
        assert {"health_score", "health_electrical", "VR", "PF", "OLI_pct"} <= set(d["frames"].columns)
    ok = api.whatif_day("S2", t, 0.62, 35)
    assert ok["alerts"] == [] and ok["frames"]["health_band"].iloc[-1] == "Green"
    daily = api.whatif_day("S2", t, 0.62, 35, load_profile="daily")
    assert len(daily["frames"]) == 2 * 96 and daily["alerts"] == []
    assert daily["frames"]["load_pu"].max() == pytest.approx(0.62, abs=0.02)


def test_whatif_day_electrical_inputs():
    d = api.whatif_day("S2", "2026-04-16T12:00", 0.62, 30, voltage_pu=0.9, pf=0.8, unbalance_pct=20)
    types = {a["type"] for a in d["alerts"]}
    assert {"current_unbalance", "voltage_low"} <= types
    end = d["frames"].iloc[-1]
    assert end["PF"] == pytest.approx(0.8, abs=0.02) and end["health_electrical"] < 60
    with pytest.raises(ValueError):
        api.whatif_day("S2", None, 0.62, 30, load_profile="weekly")


def test_findings_groups_and_parts():
    f = api.findings("S2", "2026-04-28T00:00")
    causes = {g["cause"] for g in f["findings"]}
    assert {"Overloading", "Insulation"} <= causes
    drift = next(g for g in f["findings"] if g["type"] == "residual_drift")
    assert "radiators" in drift["parts"] and drift["recommendation"]["test"]
    assert api.findings("S2", "2026-04-01T06:00")["findings"] == []          # before the fault: nothing
    s = api.findings("S5")["stress"]
    assert s["triggered"] and s["qualifying"] >= s["moderate_limit"] and s["cum_i2t_pu2s"] > 0


@pytest.mark.parametrize("dataset_id", IDS)
def test_frames(dataset_id):
    r = api.get_run(dataset_id)
    f = api.frames(dataset_id)
    assert isinstance(f, pd.DataFrame) and len(f) == len(r.trend)
    assert {"timestamp", "OTI_C", "twin_oil_C", "health_score", "health_band", "health_thermal"} <= set(f.columns)
    assert (f["health_score"].to_numpy() == r.health_series["score"].to_numpy()).all()
    sub = api.frames(dataset_id, fields=["OTI_C"], every=10)
    assert list(sub.columns) == ["timestamp", "OTI_C"] and len(sub) == len(range(0, len(r.trend), 10))
    with pytest.raises(ValueError):
        api.frames(dataset_id, fields=["nope"])
