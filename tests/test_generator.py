"""Generated campus data (FINAL_PRD.md §5): reproducible, amps, physical Normal, faults in the plant only."""
import numpy as np
import pandas as pd
import pytest
from transformer_thermal_model.aging import aging_rate_profile
from transformer_thermal_model.transformer import PaperInsulationType

from contracts.canonical import validate
from sim.generator import SCENARIO_IDS, generate

I_RATED = 1391
SKIP = ["gt_fault", "gt_type"]


@pytest.fixture(scope="module")
def runs():
    return {s: generate(s, seed=0) for s in SCENARIO_IDS}


def onset(t):
    return t.loc[t["gt_fault"] == 1, "timestamp"].iloc[0]


def test_reproducible_with_fixed_seed(runs):
    again, _ = generate("N", seed=0)
    pd.testing.assert_frame_equal(runs["N"][0], again)
    other, _ = generate("N", seed=1)
    assert not np.allclose(other["OTI_C"], again["OTI_C"])


def test_window_and_contract(runs):
    for s, (t, e) in runs.items():
        assert len(t) == 2880, s
        assert (t["timestamp"].diff().dropna() == pd.Timedelta("15min")).all()
        assert validate(t, e) == [], s
        assert t["simulated"].all() and (t["source"] == "generated_sim").all()


def test_currents_are_amps(runs):
    t = runs["N"][0]
    assert t["I_mean"].median() > 100
    np.testing.assert_allclose(t["I_mean"], t["loading_pct"] / 100 * I_RATED, rtol=1e-3)


def test_normal_is_physical_and_quiet(runs):
    t, e = runs["N"]
    assert t["gt_fault"].sum() == 0 and e.empty
    assert 0.55 <= t["loading_pct"].max() / 100 <= 0.85
    assert (t["OTI_C"] > t["ATI_C"]).all()
    assert t["OTI_C"].max() < 85 and t["WTI_C"].max() < 98      # no Normal false alarms
    assert 45 < t["OTI_C"].quantile(0.99) < 85
    rate = aging_rate_profile(pd.Series(t["WTI_C"].to_numpy(), index=t["timestamp"].dt.tz_localize(None)),
                              PaperInsulationType.NORMAL)
    assert rate.mean() < 1


@pytest.mark.parametrize("sid", [s for s in SCENARIO_IDS if s != "N"])
def test_identical_to_normal_before_onset(runs, sid):
    t, n = runs[sid][0], runs["N"][0]
    before = t["timestamp"] < onset(t) - pd.Timedelta("2h")
    pd.testing.assert_frame_equal(t.loc[before].drop(columns=SKIP), n.loc[before].drop(columns=SKIP),
                                  check_exact=False, atol=0.05)


def test_s1_overload(runs):
    t = runs["S1"][0]
    g = t[t["gt_fault"] == 1]
    assert set(g["timestamp"].dt.day) == {24, 25, 26}
    assert 108 <= g["loading_pct"].max() <= 127                       # 1.10-1.25 pu
    peaks = g.groupby(g["timestamp"].dt.day)["WTI_C"].max()
    assert (peaks > 98).all()                                         # crosses the hot-spot warning each day
    assert 115 <= peaks.max() <= 128                                  # briefly ~120 C, not 170
    assert (t["WTI_C"] > 115).sum() * 15 <= 120                       # "briefly": at most 2 h above 115 C


def test_s2_cooling_drift(runs):
    t, n = runs["S2"][0], runs["N"][0]
    late = t["timestamp"] >= pd.Timestamp("2026-04-27", tz="Asia/Kolkata")
    assert (t.loc[late, "OTI_C"] - n.loc[late, "OTI_C"]).mean() > 3
    np.testing.assert_allclose(t["I_mean"], n["I_mean"])  # load unchanged: only cooling differs


def test_s3_unbalance(runs):
    t = runs["S3"][0]
    ub = (t[["IR", "IY", "IB"]].sub(t["I_mean"], axis=0)).abs().max(axis=1) / t["I_mean"] * 100
    on = t["gt_fault"] == 1
    assert ub[on].median() > 10 and ub[~on].max() < 4


def test_s4_leak_vs_theft(runs):
    n = runs["N"][0]
    leak, theft = runs["S4a"][0], runs["S4b"][0]
    assert (n["OLI_pct"] - leak["OLI_pct"]).iloc[-96:].mean() == pytest.approx(22, abs=1.5)
    d = theft["OLI_pct"].diff(4)  # change within 1 h
    k = d.idxmin()
    assert d[k] <= -8 and theft.loc[k, "timestamp"].hour < 5           # night step
    np.testing.assert_allclose(theft["OTI_C"], n["OTI_C"])            # no thermal cause


def test_s5_events_only(runs):
    t, e = runs["S5"]
    n = runs["N"][0]
    assert len(e) == 3 and (e["event_type"] == "through_fault").all()
    np.testing.assert_allclose(e["i2t_pu2s"], e["peak_pu"] ** 2 * e["duration_ms"] / 1000)
    pd.testing.assert_frame_equal(t.drop(columns=SKIP), n.drop(columns=SKIP))  # 15-min trend can't see them
    assert t["gt_fault"].sum() == 3


def test_runs_offline(no_network):
    t, _ = generate("N", seed=0)
    assert len(t) == 2880
