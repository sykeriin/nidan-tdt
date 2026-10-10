"""Brief (status, diagnosis, work order), forecast (headroom, Monte Carlo life, 24 h) and the detailed physics model."""
import shutil

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from analytics import brief
from dt import api
from server import app as appmod
from sim.generator import generate
from twin import detailed, forecast, physics, profile
from twin.engine import TwinEngine

TZ = "Asia/Kolkata"
T1 = profile.resolve({"rating_kVA": 1000, "lv_voltage_V": 415})


def at(day_hour: str) -> pd.Timestamp:
    return pd.Timestamp(f"2026-04-{day_hour}", tz=TZ)


# ---------------------------------------------------------------- detailed model
def test_detailed_model_equals_iec_at_rated_conditions():
    m = detailed.DetailedModel(T1)
    oil, hs, _ = m.steady_state(1.0, 30.0)
    c = physics.steady_chain(T1, 1.0, 30.0)
    assert oil == pytest.approx(c["top_oil_C"], abs=0.05) and hs == pytest.approx(c["hot_spot_C"], abs=0.05)


@pytest.mark.parametrize("K, amb", [(0.3, 30), (0.6, 35), (1.0, 20), (1.2, 40)])
def test_detailed_model_stays_close_to_iec_elsewhere_but_not_identical(K, amb):
    oil, hs, _ = detailed.DetailedModel(T1).steady_state(K, amb)
    c = physics.steady_chain(T1, K, amb)
    # Within a few kelvin of the standard even at extremes; the gap is copper loss growing with temperature, not an error.
    assert abs(oil - c["top_oil_C"]) < 8 and abs(hs - c["hot_spot_C"]) < 12


def test_winding_copper_loss_rises_with_temperature_and_eddy_falls():
    m = detailed.DetailedModel(T1)
    cold, hot = m.losses(40.0, 1.0), m.losses(100.0, 1.0)
    assert hot["i2r"] > cold["i2r"] and hot["eddy"] < cold["eddy"] and hot["core"] == cold["core"]


def test_harmonics_add_loss_and_heat():
    m = detailed.DetailedModel(T1)
    base, k6 = m.steady_state(1.0, 30.0)[0], m.steady_state(1.0, 30.0, kfactor=6.0)[0]
    assert k6 > base + 5
    assert m.losses(80.0, 1.0, kfactor=6.0)["eddy"] == pytest.approx(6 * m.losses(80.0, 1.0)["eddy"])


def test_detailed_step_response_is_nonlinear_and_settles():
    r = physics.compare_models(T1, 0.4, 1.2, 30.0, 900)
    oil = np.array(r["detailed"]["top_oil_C"])
    assert np.all(np.diff(oil) >= -1e-6) and oil[-1] == pytest.approx(r["steady_after"]["detailed"]["top_oil_C"], abs=6)
    assert r["time_constants"]["detailed_63pct_min"] != r["time_constants"]["iec_63pct_min"]


def test_mass_implied_time_constant_needs_masses():
    assert detailed.implied_time_constant_h(T1) is None
    sch = profile.resolve({"rating_kVA": 1250, "lv_voltage_V": 433, "total_loss_100_W": 8400, "total_loss_50_W": 3220,
                           "top_oil_rise_K": 40, "oil_mass_kg": 1500, "total_mass_kg": 6500})
    assert 2 < detailed.implied_time_constant_h(sch)["tau_h"] < 20


def test_ageing_models_agree_at_reference_and_part_company_away_from_it():
    m = detailed.ageing_models()
    hs = m["hot_spot_C"]
    by = {x["id"]: x["rate"] for x in m["models"]}
    assert by["iec_normal"][hs.index(98.0)] == pytest.approx(1.0, abs=1e-3) and by["arrhenius_111"][hs.index(98.0)] == pytest.approx(1.0, abs=1e-3)
    assert by["arrhenius_equiv"][hs.index(98.0)] == pytest.approx(1.0, abs=1e-3)
    i = hs.index(140.0)
    assert by["arrhenius_111"][i] < by["iec_normal"][i] and by["iec_upgraded"][i] < by["iec_normal"][i]


def test_twin_still_catches_faults_when_the_plant_runs_different_physics():
    """The strongest honesty check: a plant that is not the twin's own equations."""
    normal, _ = generate("N", seed=0, asset=T1, plant="detailed")
    s2, _ = generate("S2", seed=0, asset=T1, plant="detailed")
    twin_n, twin_s2 = TwinEngine(T1).run(normal), TwinEngine(T1).run(s2)
    rmse = float(np.sqrt((twin_n["residual_oil_C"] ** 2).mean()))
    assert 0.5 < rmse < 4.0                                   # a real model-form error, not zero, not huge
    assert twin_s2["residual_oil_C"].tail(300).mean() > twin_n["residual_oil_C"].tail(300).mean() + 2


def test_generator_rejects_unknown_plant():
    with pytest.raises(ValueError, match="plant"):
        generate("N", asset=T1, plant="quantum")


# ---------------------------------------------------------------- forecast
def test_headroom_shrinks_as_it_gets_hotter():
    cool, hot = forecast.headroom(T1, 15.0)["pu"], forecast.headroom(T1, 38.0)["pu"]
    assert cool > hot > 0
    assert forecast.headroom(T1, 200.0)["pu"] == 0.0


def test_time_to_limit_cases():
    assert forecast.time_to_limit(T1, 0.4, 30.0, 45.0)["status"] == "not_reached"
    assert forecast.time_to_limit(T1, 1.4, 30.0, 110.0)["status"] == "already_reached"
    r = forecast.time_to_limit(T1, 1.3, 30.0, 60.0)
    assert r["status"] == "reaches_limit" and 0 < r["hours"] < 24


def test_remaining_life_distribution_is_ordered_and_reproducible():
    run = api.get_run("N")
    kw = dict(asset=T1, trend=run.trend, t=at("26 14:00"), consumed_h=3 * 8766.0, reference_life_h=180000.0, risk_years={"high": 2, "medium": 5})
    a, b = forecast.rul_distribution(**kw, seed=1), forecast.rul_distribution(**kw, seed=1)
    assert a == b
    assert a["years_p10"] <= a["years_p50"] <= a["years_p90"]
    assert np.all(np.diff(a["fan"]["p50"]) >= -1e-9) and a["fan"]["p10"][5] <= a["fan"]["p50"][5] <= a["fan"]["p90"][5]
    worn = forecast.rul_distribution(**{**kw, "consumed_h": 19 * 8766.0}, seed=1)
    assert worn["years_p50"] < a["years_p50"]


def test_overload_history_shortens_the_projected_life():
    n, s1 = api.get_run("N"), api.get_run("S1")
    kw = dict(asset=T1, t=at("27 12:00"), consumed_h=3 * 8766.0, reference_life_h=180000.0, risk_years={"high": 2, "medium": 5}, seed=3)
    assert forecast.rul_distribution(trend=s1.trend, **kw)["years_p50"] <= forecast.rul_distribution(trend=n.trend, **kw)["years_p50"]


def test_trip_risk_is_zero_for_a_healthy_unit_and_forecast_has_a_band():
    run = api.get_run("N")
    assert forecast.trip_risk_30d(T1, run.trend, at("26 14:00"))["probability"] == 0.0
    f = forecast.forecast_24h(run.trend, T1, at("26 14:00"))
    assert f["available"] and len(f["t"]) == len(f["hot_spot_C"]) == 96
    assert all(lo <= v <= hi for lo, v, hi in zip(f["top_oil_lo"], f["top_oil_C"], f["top_oil_hi"]))


def test_forecast_declines_politely_without_enough_data():
    run = api.get_run("N")
    assert forecast.forecast_24h(run.trend.head(3), T1, at("01 00:30"))["available"] is False
    assert forecast.forecast_24h(run.trend.drop(columns=["amb_C"]), T1, at("26 14:00"))["available"] is False


# ---------------------------------------------------------------- brief
def test_brief_good_on_normal_and_says_so_in_numbers():
    b = brief.brief(api.get_run("N"), at("26 14:00"))
    assert b["level"] == "good" and "good condition" in b["sentence"] and "°C" in b["sentence"]
    assert b["advice"]["priority"] == "Routine" and not b["advice"]["actions"]
    assert all(d["share"] == 0 for d in b["diagnosis"])


@pytest.mark.parametrize("sid, when, top", [
    ("S1", "24 14:00", "overload"), ("S2", "29 14:00", "cooling"), ("S3", "26 14:00", "unbalance"),
    ("S4b", "25 06:00", "oil"), ("S5", "27 18:00", "short_circuit"),
])
def test_brief_ranks_the_injected_fault_first(sid, when, top):
    b = brief.brief(api.get_run(sid), at(when))
    assert b["level"] in ("watch", "critical") and b["diagnosis"][0]["fault"] == top
    assert b["advice"]["actions"] and b["advice"]["actions"][0]["action"]
    assert sum(d["share"] for d in b["diagnosis"]) == pytest.approx(1.0, abs=0.02)


def test_brief_marks_unobservable_classes_instead_of_guessing():
    run = api.get_run("N")
    run2 = type(run)(**{**run.__dict__, "capabilities": {**run.capabilities, "oil_leak_theft": False, "through_fault": False}})
    d = {x["fault"]: x for x in brief.brief(run2, at("26 14:00"))["diagnosis"]}
    assert d["oil"]["observable"] is False and d["oil"]["why"] == "Not observable with these inputs." and d["oil"]["evidence"] == 0


def test_brief_kpis_and_no_data_cases():
    b = brief.brief(api.get_run("S1"), at("26 14:00"))
    assert 0 < b["kpis"]["headroom"]["pu"] < 3 and b["kpis"]["time_to_limit"]["status"] in ("not_reached", "reaches_limit", "already_reached")
    assert brief.brief(api.get_run("N"), pd.Timestamp("2020-01-01", tz=TZ))["level"] == "nodata"


# ---------------------------------------------------------------- HTTP
@pytest.fixture(scope="module")
def client():
    return TestClient(appmod.app)


def test_brief_and_outlook_endpoints(client):
    r = client.get("/api/datasets/S2/brief", params={"t": "2026-04-29T14:00:00"})
    assert r.status_code == 200 and r.json()["diagnosis"][0]["fault"] == "cooling"
    o = client.get("/api/datasets/S2/outlook", params={"t": "2026-04-29T14:00:00"})
    j = o.json()
    assert o.status_code == 200 and j["rul"]["years_p10"] <= j["rul"]["years_p90"] and j["forecast"]["available"]
    assert client.get("/api/datasets/S2/brief", params={"t": "nonsense"}).status_code == 422
    assert client.get("/api/datasets/nope/brief", params={"t": "2026-04-29T14:00:00"}).status_code == 404


def test_detailed_physics_endpoints(client):
    body = {"values": {"rating_kVA": 1000, "lv_voltage_V": 415}, "from_pu": 0.4, "to_pu": 1.1, "ambient_C": 30, "minutes": 120, "k_factor": 1}
    r = client.post("/api/physics/detailed", json=body)
    assert r.status_code == 200 and len(r.json()["detailed"]["top_oil_C"]) == 121
    assert client.post("/api/physics/detailed", json={**body, "k_factor": 99}).status_code == 422
    a = client.get("/api/physics/ageing-models")
    assert a.status_code == 200 and len(a.json()["models"]) == 4
    w = client.post("/api/datasets/S1/whatif", json={"model": "detailed", "k_factor": 3, "load_mult": 1.1})
    assert w.status_code == 200 and w.json()["summary"]["inputs"]["model"] == "detailed"
    assert client.post("/api/datasets/S1/whatif", json={"model": "iec", "k_factor": 3}).status_code == 400


def test_simulate_with_detailed_plant_end_to_end(client):
    r = client.post("/api/simulate", json={"scenario": "S2", "values": {"rating_kVA": 500, "lv_voltage_V": 415}, "plant": "detailed"})
    assert r.status_code == 201, r.text
    did = r.json()["dataset_id"]
    try:
        run = client.get(f"/api/datasets/{did}/run").json()
        assert "detailed physics" in run["name"] and "residual_drift" in {a["type"] for a in run["analysis"]["alerts"]}
    finally:
        shutil.rmtree(appmod.ROOT / "data" / "cache" / "runs" / did, ignore_errors=True)
        reg = appmod._registry()
        reg.pop(did, None)
        appmod.REGISTRY.write_text(__import__("json").dumps(reg), encoding="utf-8")
    assert client.post("/api/simulate", json={"scenario": "N", "values": {"rating_kVA": 500}, "plant": "x"}).status_code == 400


def test_utc_query_times_give_the_same_answer_as_local_ones():
    """The browser sends UTC; hour-of-day profiles must still use the data's own (IST) clock."""
    local = api.outlook("S2", pd.Timestamp("2026-04-29 14:00", tz=TZ), runs=200)
    utc = api.outlook("S2", pd.Timestamp("2026-04-29 08:30", tz="UTC"), runs=200)
    assert local["forecast"]["t"] == utc["forecast"]["t"] and local["rul"] == utc["rul"]
    b1, b2 = api.brief("S2", pd.Timestamp("2026-04-29 14:00", tz=TZ)), api.brief("S2", pd.Timestamp("2026-04-29 08:30", tz="UTC"))
    assert b1["sentence"] == b2["sentence"]
