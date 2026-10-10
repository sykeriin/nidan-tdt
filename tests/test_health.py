import numpy as np
import pandas as pd
import pytest

from analytics import health
from analytics.common import load_thresholds, make_alert
from eval.scenarios import load_scenario, capabilities

TH = load_thresholds()
CAPS = capabilities() | {"through_fault": True}   # as if an event log were present, so every sub-score is on


def _frame(scenario="N", days=30):
    return load_scenario(scenario, days=days)[0]


def test_normal_is_green_and_bounded():
    s = health.compute_series(_frame("N"), [], CAPS, TH)
    assert list(s.columns) == ["timestamp", "score", "band", *health.SUB_SCORES, "capped"]
    assert s.score.between(0, 100).all()
    assert (s.band == "Green").all()
    h = health.compute(_frame("N"), [], CAPS, TH)
    assert h.band == "Green" and not h.capped
    assert set(h.components) == set(health.SUB_SCORES)
    assert sum(h.weights.values()) == pytest.approx(1.0)


def test_s1_scores_worse_than_normal():
    n = health.compute_series(_frame("N"), [], CAPS, TH)
    s1 = health.compute_series(_frame("S1"), [], CAPS, TH)
    assert s1.score.min() < n.score.min() - 15            # real S1: short overload (1.10-1.25 pu), min ~71 vs ~92
    assert (s1.band == "Yellow").any() and s1.thermal.min() < 40
    assert s1.score.between(0, 100).all()
    from analytics.pipeline import analyze               # with S1's own critical alerts the weakest-link cap -> Red
    res = analyze(_frame("S1"), load_scenario("S1")[1], CAPS, TH)
    red = health.compute_series(_frame("S1"), res.alerts, CAPS, TH)
    assert (red.band == "Red").any()


def test_s3_unbalance_lowers_electrical_only():
    h = health.compute(_frame("S3"), [], CAPS, TH)
    assert h.components["electrical"] < 80
    assert h.components["thermal"] == pytest.approx(100.0)


def test_weights_renormalize_when_caps_missing():
    caps = capabilities() | {"oil_leak_theft": False, "through_fault": False, "unbalance": False, "voltage_quality": False}
    h = health.compute(_frame("N"), [], caps, TH)
    assert set(h.components) == {"thermal", "ageing", "loading"}
    assert h.weights["thermal"] == pytest.approx(30 / 70)
    assert sum(h.weights.values()) == pytest.approx(1.0)


def test_missing_columns_disable_subscores_without_crashing():
    df = _frame("N")[["timestamp", "load_pu"]]
    h = health.compute(df, [], CAPS, TH)
    assert set(h.components) == {"loading", "fault_stress"}
    assert health.compute(pd.DataFrame(), [], {}, TH).score == 100.0


def test_meter_only_still_scores():
    df = _frame("S1").drop(columns=["OTI_C", "WTI_C", "twin_oil_C", "twin_hs_C", "residual_oil_C", "aging_rate", "days_aged_cum"])
    caps = CAPS | {"residual_fidelity": False, "ageing_rul": False, "thermal_twin": False}
    s = health.compute_series(df, [], caps, TH)
    assert s.score.between(0, 100).all() and s.score.notna().all()
    h = health.compute(df, [], caps, TH)
    assert "thermal" not in h.components and "ageing" not in h.components
    assert s.loading.min() < 60 and s.score.min() < 90  # overload still visible through loading


def test_weakest_link_cap_and_window():
    df = _frame("N", days=5)
    t = df.timestamp.iloc[200]
    crit = make_alert(t, "hot_spot_high", "critical", "rule")
    s = health.compute_series(df, [crit], CAPS, TH)
    inside = (df.timestamp >= t) & (df.timestamp < t + pd.Timedelta(hours=24))
    assert (s.score[inside] <= 40).all() and s.capped[inside].all()
    assert (s.band[inside] == "Red").all()
    assert not s.capped[df.timestamp < t].any()
    assert (s.score[df.timestamp >= t + pd.Timedelta(hours=24)] > 90).all()


def test_cap_ignores_warning_and_sensor_alerts():
    df = _frame("N", days=3)
    t = df.timestamp.iloc[100]
    alerts = [make_alert(t, "top_oil_high", "warning", "rule"), make_alert(t, "hot_spot_high", "critical", "rule", origin="sensor")]
    s = health.compute_series(df, alerts, CAPS, TH)
    assert not s.capped.any()


def test_capped_false_when_score_already_below_cap():
    df = _frame("S1").copy()
    peak = df["load_pu"].idxmax()
    rows = slice(peak - 4, peak + 4)                              # force every sub-score bad at the overload peak
    df.loc[rows, ["OTI_C", "twin_oil_C"]] += 40.0
    df.loc[rows, ["WTI_C", "twin_hs_C"]] += 60.0
    df.loc[rows, ["load_pu"]] *= 1.6
    df.loc[rows, "loading_pct"] *= 1.6
    df.loc[rows, "IR"] *= 2.0
    df.loc[rows, "OLI_pct"] = 40.0
    df.loc[rows, ["aging_rate", "aging_rate_actual"]] = 50.0
    s0 = health.compute_series(df, [], CAPS, TH)
    i = int(s0.score.idxmin())
    assert s0.score[i] < 40
    t = df.timestamp.iloc[i]
    s = health.compute_series(df, [make_alert(t, "hot_spot_high", "critical", "rule")], CAPS, TH)
    assert s.score[i] == pytest.approx(s0.score[i]) and not s.capped[i]


def test_leak_and_through_fault_alerts_lower_subscores():
    df = _frame("N", days=3)
    t = df.timestamp.iloc[150]
    base = health.compute_series(df, [], CAPS, TH)
    alerts = [make_alert(t, "oil_leak", "warning", "rule"), make_alert(t, "through_fault", "warning", "rule"),
              make_alert(t, "through_fault_stress", "critical", "rule")]
    s = health.compute_series(df, alerts, CAPS, TH)
    assert s.integrity.iloc[150] <= 60 and s.fault_stress.iloc[150] <= 30
    assert s.integrity.iloc[-1] == base.integrity.iloc[-1]  # leak flag expires, stress does not
    assert s.fault_stress.iloc[-1] <= 30
    assert s.integrity.iloc[100] == base.integrity.iloc[100]


def test_compute_matches_last_series_row():
    df = _frame("S4a")
    s = health.compute_series(df, [], CAPS, TH)
    h = health.compute(df, [], CAPS, TH)
    assert h.score == pytest.approx(s.score.iloc[-1])
    assert h.band == s.band.iloc[-1]
    assert np.isfinite(h.score)
