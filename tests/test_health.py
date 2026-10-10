import numpy as np
import pandas as pd
import pytest

from analytics import health
from analytics.common import load_thresholds, make_alert
from tests.mock_data import make_mock, mock_caps

TH = load_thresholds()


def _frame(scenario="N", days=30):
    return make_mock(scenario, days=days)[0]


def test_normal_is_green_and_bounded():
    s = health.compute_series(_frame("N"), [], mock_caps(), TH)
    assert list(s.columns) == ["timestamp", "score", "band", *health.SUB_SCORES, "capped"]
    assert s.score.between(0, 100).all()
    assert (s.band == "Green").all()
    h = health.compute(_frame("N"), [], mock_caps(), TH)
    assert h.band == "Green" and not h.capped
    assert set(h.components) == set(health.SUB_SCORES)
    assert sum(h.weights.values()) == pytest.approx(1.0)


def test_s1_scores_worse_than_normal():
    n = health.compute_series(_frame("N"), [], mock_caps(), TH)
    s1 = health.compute_series(_frame("S1"), [], mock_caps(), TH)
    assert s1.score.min() < n.score.min() - 20
    assert (s1.band == "Red").any()
    assert s1.score.between(0, 100).all()


def test_s3_unbalance_lowers_electrical_only():
    h = health.compute(_frame("S3"), [], mock_caps(), TH)
    assert h.components["electrical"] < 80
    assert h.components["thermal"] == pytest.approx(100.0)


def test_weights_renormalize_when_caps_missing():
    caps = mock_caps() | {"oil_level": False, "through_fault": False, "unbalance": False, "voltage_quality": False}
    h = health.compute(_frame("N"), [], caps, TH)
    assert set(h.components) == {"thermal", "ageing", "loading"}
    assert h.weights["thermal"] == pytest.approx(30 / 70)
    assert sum(h.weights.values()) == pytest.approx(1.0)


def test_missing_columns_disable_subscores_without_crashing():
    df = _frame("N")[["timestamp", "load_pu"]]
    h = health.compute(df, [], mock_caps(), TH)
    assert set(h.components) == {"loading", "fault_stress"}
    assert health.compute(pd.DataFrame(), [], {}, TH).score == 100.0


def test_meter_only_still_scores():
    df = _frame("S1").drop(columns=["OTI_C", "WTI_C", "twin_oil_C", "twin_hs_C", "residual_oil_C", "aging_rate", "days_aged_cum"])
    caps = mock_caps(meter_only=True) | {"ageing_rul": False, "thermal_twin": False}
    s = health.compute_series(df, [], caps, TH)
    assert s.score.between(0, 100).all() and s.score.notna().all()
    h = health.compute(df, [], caps, TH)
    assert "thermal" not in h.components and "ageing" not in h.components
    assert s.score.min() < 70  # overload still visible through loading


def test_weakest_link_cap_and_window():
    df = _frame("N", days=5)
    t = df.timestamp.iloc[200]
    crit = make_alert(t, "hot_spot_high", "critical", "rule")
    s = health.compute_series(df, [crit], mock_caps(), TH)
    inside = (df.timestamp >= t) & (df.timestamp < t + pd.Timedelta(hours=24))
    assert (s.score[inside] <= 40).all() and s.capped[inside].all()
    assert (s.band[inside] == "Red").all()
    assert not s.capped[df.timestamp < t].any()
    assert (s.score[df.timestamp >= t + pd.Timedelta(hours=24)] > 90).all()


def test_cap_ignores_warning_and_sensor_alerts():
    df = _frame("N", days=3)
    t = df.timestamp.iloc[100]
    alerts = [make_alert(t, "top_oil_high", "warning", "rule"), make_alert(t, "hot_spot_high", "critical", "rule", origin="sensor")]
    s = health.compute_series(df, alerts, mock_caps(), TH)
    assert not s.capped.any()


def test_capped_false_when_score_already_below_cap():
    df = _frame("S1")
    s0 = health.compute_series(df, [], mock_caps(), TH)
    i = int(s0.score.idxmin())
    t = df.timestamp.iloc[i]
    s = health.compute_series(df, [make_alert(t, "hot_spot_high", "critical", "rule")], mock_caps(), TH)
    assert s.score[i] == pytest.approx(30.0) and not s.capped[i]


def test_leak_and_through_fault_alerts_lower_subscores():
    df = _frame("N", days=3)
    t = df.timestamp.iloc[150]
    base = health.compute_series(df, [], mock_caps(), TH)
    alerts = [make_alert(t, "oil_leak", "warning", "rule"), make_alert(t, "through_fault", "warning", "rule"),
              make_alert(t, "through_fault_stress", "critical", "rule")]
    s = health.compute_series(df, alerts, mock_caps(), TH)
    assert s.integrity.iloc[150] <= 60 and s.fault_stress.iloc[150] <= 30
    assert s.integrity.iloc[-1] == base.integrity.iloc[-1]  # leak flag expires, stress does not
    assert s.fault_stress.iloc[-1] <= 30
    assert s.integrity.iloc[100] == base.integrity.iloc[100]


def test_compute_matches_last_series_row():
    df = _frame("S4")
    s = health.compute_series(df, [], mock_caps(), TH)
    h = health.compute(df, [], mock_caps(), TH)
    assert h.score == pytest.approx(s.score.iloc[-1])
    assert h.band == s.band.iloc[-1]
    assert np.isfinite(h.score)
