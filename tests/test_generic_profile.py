"""Generic distribution-transformer profile: any rating in, tagged parameters out, physics checked against the library."""
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from server import app as appmod
from sim.generator import generate
from twin import physics, profile, thermal
from twin.engine import TwinEngine

SCHNEIDER = {"rating_kVA": 1250, "lv_voltage_V": 433, "total_loss_100_W": 8400, "total_loss_50_W": 3220, "top_oil_rise_K": 40}


# ---------------------------------------------------------------- profile
def test_rating_only_profile_is_complete_and_tagged():
    a = profile.resolve({"rating_kVA": 630, "lv_voltage_V": 415})
    assert a["i_rated_A"] == pytest.approx(630e3 / (np.sqrt(3) * 415), abs=0.1) and a["tags"]["i_rated_A"] == "Calculated"
    assert a["load_loss_W"] == pytest.approx(6300) and a["tags"]["load_loss_W"] == "Assumed"
    for key, (_, default, _, _) in profile.THERMAL.items():
        assert a[key] == default and a["tags"][key] == profile.IEC_TAG
    assert a["tags"]["rating_kVA"] == "User input"


def test_losses_derived_from_two_total_loss_points():
    pk, p0 = profile.split_losses(8400, 3220)
    assert (pk, p0) == (pytest.approx(6906.7, abs=0.1), pytest.approx(1493.3, abs=0.1))
    assert p0 + pk == pytest.approx(8400) and p0 + 0.25 * pk == pytest.approx(3220)   # reproduces both inputs
    a = profile.resolve(SCHNEIDER)
    assert a["tags"]["load_loss_W"] == "Derived" and a["tags"]["no_load_loss_W"] == "Derived"
    assert a["i_rated_A"] == pytest.approx(1666.7, abs=0.1)                           # matches the plate's 1666.72 A


def test_nameplate_beats_defaults_and_given_losses_beat_totals():
    a = profile.resolve({**SCHNEIDER, "load_loss_W": 7000, "no_load_loss_W": 1400})
    assert (a["load_loss_W"], a["no_load_loss_W"]) == (7000, 1400) and a["top_oil_rise_K"] == 40
    assert a["tags"]["top_oil_rise_K"] == "User input"


@pytest.mark.parametrize("bad, msg", [
    ({}, "rating"), ({"rating_kVA": -5}, "positive"), ({"rating_kVA": "abc"}, "number"),
    ({"rating_kVA": 500, "total_loss_100_W": 100, "total_loss_50_W": 200}, "larger"),
    ({"rating_kVA": 500, "total_loss_100_W": 1000, "total_loss_50_W": 10}, "negative no-load"),
])
def test_bad_profiles_are_refused_with_a_readable_reason(bad, msg):
    with pytest.raises(ValueError, match=msg):
        profile.resolve(bad)


def test_manufacture_date_gives_years_in_service():
    from datetime import date
    a = profile.resolve({"rating_kVA": 1250, "manufacture_year": 2025, "manufacture_month": 7}, today=date(2026, 10, 10))
    assert a["years_in_service"] == pytest.approx(1.2) and a["tags"]["years_in_service"] == "Calculated"


def test_twin_uses_the_profile_thermal_parameters():
    cool = TwinEngine(profile.resolve({**SCHNEIDER})).tr.specs
    default = TwinEngine(profile.resolve({"rating_kVA": 1250, "lv_voltage_V": 433})).tr.specs
    assert cool.top_oil_temp_rise == 40 and default.top_oil_temp_rise == 60


# ---------------------------------------------------------------- physics vs the library
@pytest.mark.parametrize("raw", [{"rating_kVA": 1000, "lv_voltage_V": 415}, SCHNEIDER, {"rating_kVA": 250, "lv_voltage_V": 415}])
@pytest.mark.parametrize("load", [0.0, 0.3, 0.7, 1.0, 1.25])
def test_closed_form_equations_match_the_library_for_any_rating(raw, load):
    c = physics.steady_chain(profile.resolve(raw), load, 32.0)
    assert c["library_check"]["max_abs_diff_K"] < 0.01
    ids = [s["id"] for s in c["steps"]]
    assert ids == ["load", "losses", "top_oil", "gradient", "hot_spot", "ageing"]


def test_ageing_doubles_every_6_kelvin_and_is_one_at_98():
    a = profile.resolve({"rating_kVA": 1000, "lv_voltage_V": 415})
    rates = {}
    for load in (0.9, 1.0):
        c = physics.steady_chain(a, load, 20.0)
        rates[load] = (c["hot_spot_C"], c["ageing_rate"])
    (h1, r1), (h2, r2) = rates[0.9], rates[1.0]
    assert r2 / r1 == pytest.approx(2 ** ((h2 - h1) / 6), rel=0.02)


def test_lower_rated_rise_runs_cooler():
    hot = physics.steady_chain(profile.resolve({"rating_kVA": 1000}), 1.0, 30)["top_oil_C"]
    cool = physics.steady_chain(profile.resolve({"rating_kVA": 1000, "top_oil_rise_K": 40}), 1.0, 30)["top_oil_C"]
    assert cool < hot


def test_step_response_oil_is_slow_and_winding_is_fast():
    r = physics.step_response(profile.resolve({"rating_kVA": 1000}), 0.3, 1.0, 30, 600)
    oil, hs = np.array(r["top_oil_C"]), np.array(r["hot_spot_C"])
    gap = hs - oil
    assert np.all(np.diff(oil) >= -1e-6) and oil[-1] == pytest.approx(r["final"]["top_oil_C"], abs=2.5)
    assert (oil[30] - oil[0]) < 0.25 * (oil[-1] - oil[0])           # oil has barely moved after 30 min (tau 180 min)
    assert gap[30] > 0.9 * gap[-1]                                  # winding gradient is there within ~30 min (tau 4 min)
    assert r["time_constants_min"] == {"oil": 180.0, "winding": 4.0}


def test_whatif_with_no_change_equals_baseline_and_more_load_ages_faster():
    trend, _ = generate("N", seed=0)
    a = profile.resolve({"rating_kVA": 1000, "lv_voltage_V": 415})
    same, s0 = physics.whatif(trend, a, 1.0, 0.0, 1.0)
    assert np.allclose(same["base_hot_spot_C"], same["whatif_hot_spot_C"], equal_nan=True)
    assert s0["base"] == s0["whatif"]
    _, s1 = physics.whatif(trend, a, 1.3, 0.0, 1.0)
    assert s1["whatif"]["equivalent_days_used"] > 5 * s1["base"]["equivalent_days_used"]
    _, s2 = physics.whatif(trend, a, 1.0, 0.0, 1.3)
    assert s2["whatif"]["peak_top_oil_C"] > s2["base"]["peak_top_oil_C"]


@pytest.mark.parametrize("kwargs", [{"load_mult": 5}, {"ambient_offset_C": 99}, {"rise_mult": 0.1}])
def test_whatif_refuses_out_of_range_inputs(kwargs):
    trend, _ = generate("N", seed=0)
    with pytest.raises(ValueError):
        physics.whatif(trend, profile.resolve({"rating_kVA": 1000}), **kwargs)


# ---------------------------------------------------------------- generator + baseline per rating
def test_generator_default_asset_is_unchanged_from_the_shipped_data():
    t, _ = generate("S2", seed=0)
    old = pd.read_csv("data/generated/trend_S2.csv")
    for c in [c for c in t.columns if t[c].dtype.kind in "fi"]:
        assert np.allclose(t[c].to_numpy(), old[c].to_numpy(), equal_nan=True), c


def test_same_scenario_scales_with_rating_in_per_unit():
    small = generate("N", seed=0, asset=profile.resolve({"rating_kVA": 250, "lv_voltage_V": 415}))[0]
    large = generate("N", seed=0, asset=profile.resolve({"rating_kVA": 1600, "lv_voltage_V": 415}))[0]
    assert np.allclose(small["loading_pct"], large["loading_pct"], rtol=0.01)       # same load in per-unit
    assert large["I_mean"].mean() / small["I_mean"].mean() == pytest.approx(1600 / 250, rel=0.01)   # amps scale with kVA


def test_generated_voltage_follows_the_asset():
    t = generate("N", seed=0, asset=profile.resolve({"rating_kVA": 1250, "lv_voltage_V": 433}))[0]
    assert t["VR"].mean() * np.sqrt(3) == pytest.approx(433, rel=0.02)


# ---------------------------------------------------------------- HTTP
@pytest.fixture(scope="module")
def client():
    return TestClient(appmod.app)


def test_presets_endpoint_lists_examples_with_tags(client):
    r = client.get("/api/presets")
    assert r.status_code == 200
    by = {p["id"]: p for p in r.json()}
    assert {"transformer-1", "schneider-1250", "generic-250"} <= set(by)
    assert by["schneider-1250"]["tags"]["load_loss_W"] == "Derived"
    assert by["transformer-1"]["values"]["i_rated_A"] == 1391


def test_profile_endpoint_completes_and_rejects(client):
    ok = client.post("/api/profile", json={"values": {"rating_kVA": 500, "lv_voltage_V": 415}})
    assert ok.status_code == 200 and ok.json()["values"]["load_loss_W"] == 5000 and ok.json()["notes"]
    bad = client.post("/api/profile", json={"values": {"rating_kVA": -1}})
    assert bad.status_code == 400 and "positive" in bad.json()["detail"]


def test_physics_endpoints(client):
    body = {"values": {"rating_kVA": 1250, "lv_voltage_V": 433, "top_oil_rise_K": 40}, "load_pu": 0.9, "ambient_C": 28}
    c = client.post("/api/physics/chain", json=body)
    assert c.status_code == 200 and len(c.json()["steps"]) == 6 and c.json()["library_check"]["max_abs_diff_K"] < 0.01
    s = client.post("/api/physics/step", json={**body, "from_pu": 0.3, "to_pu": 1.1, "minutes": 120})
    assert s.status_code == 200 and len(s.json()["t_min"]) == 121
    assert client.post("/api/physics/chain", json={**body, "load_pu": 9}).status_code == 422
    w = client.post("/api/datasets/S1/whatif", json={"load_mult": 1.1, "ambient_offset_C": 2, "rise_mult": 1.1})
    assert w.status_code == 200 and {"base_hot_spot_C", "whatif_hot_spot_C"} <= set(w.json()["series"])
    assert w.json()["summary"]["whatif"]["equivalent_days_used"] > w.json()["summary"]["base"]["equivalent_days_used"]
    assert client.post("/api/datasets/nope/whatif", json={}).status_code == 404


def test_simulate_any_rating_end_to_end(client, tmp_path):
    r = client.post("/api/simulate", json={"scenario": "S2", "values": SCHNEIDER, "name": "Test 1250 kVA S2"})
    assert r.status_code == 201, r.text
    did = r.json()["dataset_id"]
    try:
        assert did.startswith("u-") and r.json()["mode"] == "full" and r.json()["asset"]["rating_kVA"] == 1250
        run = client.get(f"/api/datasets/{did}/run").json()
        assert run["name"] == "Test 1250 kVA S2" and run["asset"]["i_rated_A"] == pytest.approx(1666.7, abs=0.1)
        types = {a["type"] for a in run["analysis"]["alerts"]}
        assert "residual_drift" in types                                    # cooling fault found on a 1250 kVA unit
        assert all(a["simulated"] for a in run["analysis"]["alerts"])        # labelled SIMULATED
    finally:
        import shutil
        shutil.rmtree(appmod.ROOT / "data" / "cache" / "runs" / did, ignore_errors=True)
        reg = appmod._registry()
        reg.pop(did, None)
        appmod.REGISTRY.write_text(__import__("json").dumps(reg), encoding="utf-8")
    assert client.post("/api/simulate", json={"scenario": "ZZ", "values": SCHNEIDER}).status_code == 400
