"""Twin engine (FINAL_PRD.md §7): batch == streaming, quiet on Normal, drifts on S2, ageing per IEC 60076-7."""
import numpy as np
import pandas as pd
import pytest
from transformer_thermal_model.aging import days_aged
from transformer_thermal_model.transformer import PaperInsulationType

from twin import ageing
from twin.engine import OUT_COLS, TwinEngine, load_config
from twin.plot import load_generated

NUM = ["twin_oil_C", "twin_hs_C", "aging_rate", "days_aged_cum", "residual_oil_C", "fidelity_rmse_C",
       "load_pu", "dt_min", "rise_low_K", "rise_high_K"]
CFG = load_config()


@pytest.fixture(scope="module")
def runs():
    return {s: TwinEngine().run(load_generated(s)) for s in ("N", "S1", "S2")}


def stream(t, **kw):
    e = TwinEngine()
    return e, pd.DataFrame([e.step(r, **kw).twin for r in t.to_dict("records")])


def assert_same(batch, streamed):
    for c in NUM:
        np.testing.assert_allclose(streamed[c].to_numpy(float), batch[c].to_numpy(float), rtol=1e-9, atol=1e-9,
                                   equal_nan=True, err_msg=c)
    for c in ("twin_restart", "fidelity_alert", "implausible_rise"):
        assert (streamed[c].to_numpy(bool) == batch[c].to_numpy(bool)).all(), c


def test_run_equals_step(runs):
    t = load_generated("S2")
    e, s = stream(t)
    assert_same(runs["S2"], s)
    assert e.current_rul() == runs["S2"].attrs["rul"]
    assert e.plausibility_verdict() == runs["S2"].attrs["plausibility"]["OTI_C"]


def test_run_equals_step_across_gap_and_missing_rows():
    t = load_generated("N").iloc[:400].copy()
    t = t.drop(index=range(150, 166)).reset_index(drop=True)      # 4 h gap -> restart
    t.loc[50:52, "I_mean"] = np.nan                                # short missing load -> no restart
    b = TwinEngine().run(t)
    assert b["twin_restart"].sum() == 2 and b.loc[150, "twin_restart"]
    assert b.loc[50:52, "twin_oil_C"].isna().all()
    assert_same(b, stream(t)[1])


def test_normal_residual_is_noise_level(runs):
    r = runs["N"]
    assert abs(r["residual_oil_C"].mean()) < 1.5     # deliberate plant/twin mismatch (rise x0.965)
    assert r["residual_oil_C"].std() < 1.0           # ~ sensor noise 0.4 C + mismatch shape
    assert r["fidelity_rmse_C"].max() < 1.5 < CFG["fidelity_alert_C"]
    assert not r["fidelity_alert"].any() and r.attrs["drift_message"] is None


def test_s2_residual_drifts_after_onset(runs):
    r = runs["S2"]
    onset = r.loc[r["gt_fault"] == 1, "timestamp"].min()
    before = r["timestamp"] < onset
    late = r["timestamp"] >= onset + pd.Timedelta(days=4)
    assert abs(r.loc[before, "residual_oil_C"].mean()) < 1.5
    assert r.loc[late, "residual_oil_C"].mean() > r.loc[before, "residual_oil_C"].mean() + 2.5
    assert not r.loc[before, "fidelity_alert"].any()
    assert r.attrs["first_drift_alert"] > onset and "model drift" in r.attrs["drift_message"]


def test_ageing_rate_iec():
    assert ageing.rate(98.0)[0] == pytest.approx(1.0)
    assert ageing.rate(100.0)[0] == pytest.approx(1.26, abs=0.005)
    assert ageing.rate(104.0)[0] == pytest.approx(2.0)


def test_cumulative_ageing_matches_library(runs):
    r = runs["N"]
    hs = pd.Series(r["twin_hs_C"].to_numpy(), index=r["timestamp"])
    assert r["days_aged_cum"].iloc[-1] == pytest.approx(days_aged(hs, PaperInsulationType.NORMAL), rel=1e-9)


def test_rul_range_drops_under_overload(runs):
    n, s1 = runs["N"].attrs["rul"], runs["S1"].attrs["rul"]
    assert n.years_low == CFG["rul_cap_years"]                 # normal load: not limited by thermal ageing
    assert s1.years_low < n.years_low and s1.recent_rate > n.recent_rate
    assert s1.years_low <= s1.years_high
    assert n.consumed_days == pytest.approx(3 * 365.25 + runs["N"]["days_aged_cum"].iloc[-1], abs=0.01)


def test_meter_only_mode(runs):
    t = load_generated("N").drop(columns=["OTI_C"])
    r = TwinEngine().run(t)
    assert r.attrs["mode"] == "meter_only"
    assert r["residual_oil_C"].isna().all() and r["fidelity_rmse_C"].isna().all()
    np.testing.assert_allclose(r["twin_oil_C"], runs["N"]["twin_oil_C"])   # temperatures still estimated
    assert r.attrs["plausibility"]["OTI_C"] == "not checked"
    assert_same(r, stream(t)[1])


def test_plausibility_in_run_output(runs):
    assert runs["N"].attrs["plausibility"]["OTI_C"] == "plausible"
    t = load_generated("N")
    t["OTI_C"] = t["ATI_C"] + 2.0
    assert TwinEngine().run(t).attrs["plausibility"]["OTI_C"] == "suspect"


def test_output_columns(runs):
    assert set(OUT_COLS) <= set(runs["N"].columns)
    assert len(runs["N"]) == 2880
