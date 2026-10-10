"""Unit tests for eval.lead_time with hand-built alerts and the mock frames."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from analytics.common import load_thresholds, make_alert
from eval.lead_time import baseline_crossings, lead_times
from tests.mock_data import START, ground_truth, make_mock

TH = load_thresholds()


def _t(days: float = 0, hours: float = 0) -> pd.Timestamp:
    return START + pd.Timedelta(days=days, hours=hours)


def test_baseline_never_fires_on_normal_and_s2():
    for sc in ("N", "S2", "S5"):
        trend, _ = make_mock(sc)
        assert all(v is None for v in baseline_crossings(trend, TH).values()), sc


def test_baseline_s1_crossings():
    trend, _ = make_mock("S1")
    c = baseline_crossings(trend, TH)
    assert c["loading_alarm"] == _t(24, 8)
    assert c["overcurrent"] is not None and c["overcurrent"] >= c["loading_alarm"]
    assert c["unbalance_warning"] is None and c["oil_level_low"] is None


def test_baseline_ignores_gt_columns():
    trend, _ = make_mock("S1")
    base = baseline_crossings(trend, TH)
    scrambled = trend.copy()
    scrambled["gt_fault"] = "x"
    assert baseline_crossings(scrambled, TH) == base


def test_baseline_since_filters_earlier_samples():
    trend, _ = make_mock("S4")
    assert baseline_crossings(trend, TH)["oil_level_low"] < _t(27)
    assert baseline_crossings(trend, TH, since=_t(27, 2.5))["oil_level_low"] == _t(27, 2.5)


def test_detected_fault_with_baseline_lead():
    trend, _ = make_mock("S1")
    gt = ground_truth("S1")
    alerts = [make_alert(_t(24, 6) + pd.Timedelta(hours=2.5), "loading_high", "warning", "rule")]
    row = lead_times(alerts, gt, trend, TH).iloc[0]
    assert row["detected"] and row["fault"] == "overload"
    assert row["first_alert_type"] == "loading_high" and row["detector"] == "rule"
    assert row["baseline_rule"] == "loading_alarm" and row["baseline_ts"] == _t(24, 8)
    assert row["lead_vs_baseline_h"] == pytest.approx(-0.5)
    assert row["lead_vs_onset_h"] == pytest.approx(-0.5)


def test_undetected_fault_has_nan_leads():
    trend, _ = make_mock("S1")
    row = lead_times([], ground_truth("S1"), trend, TH).iloc[0]
    assert not row["detected"] and row["first_alert_ts"] is None and row["detector"] is None
    assert math.isnan(row["lead_vs_baseline_h"]) and math.isnan(row["lead_vs_onset_h"])


def test_alert_outside_window_or_wrong_type_does_not_match():
    trend, _ = make_mock("S1")
    gt = ground_truth("S1")
    alerts = [
        make_alert(_t(23), "loading_high", "warning", "rule"),  # before onset
        make_alert(_t(25), "oil_low", "warning", "rule"),  # wrong type
        make_alert(_t(28, 1), "loading_high", "warning", "rule"),  # beyond end + 24 h
    ]
    assert not lead_times(alerts, gt, trend, TH).iloc[0]["detected"]


def test_baseline_never_fires_gives_nan_lead_and_none_ts():
    trend, _ = make_mock("S2")
    alerts = [make_alert(_t(22), "residual_drift", "warning", "residual")]
    row = lead_times(alerts, ground_truth("S2"), trend, TH).iloc[0]
    assert row["detected"] and row["baseline_ts"] is None
    assert math.isnan(row["lead_vs_baseline_h"])
    assert "never crossed" in row["baseline_rule"]
    assert row["lead_vs_onset_h"] == pytest.approx(-48.0)


def test_late_detection_is_negative_vs_onset_and_early_is_positive_vs_baseline():
    trend, _ = make_mock("S4")
    gt = [g for g in ground_truth("S4") if g["fault"] == "oil_leak"]
    alerts = [make_alert(_t(22), "oil_leak", "warning", "rule")]
    row = lead_times(alerts, gt, trend, TH).iloc[0]
    assert row["lead_vs_onset_h"] == pytest.approx(-48.0)
    assert row["baseline_ts"] == pd.Timestamp("2026-04-24 10:00", tz="Asia/Kolkata")
    assert row["lead_vs_baseline_h"] == pytest.approx(34.0)


def test_theft_baseline_counts_only_at_or_after_onset():
    trend, _ = make_mock("S4")
    gt = [g for g in ground_truth("S4") if g["fault"] == "oil_theft"]
    alerts = [make_alert(_t(27, 2.75), "oil_theft", "critical", "rule")]
    row = lead_times(alerts, gt, trend, TH).iloc[0]
    assert row["baseline_rule"] == "oil_level_low"
    assert row["baseline_ts"] >= gt[0]["onset"]
    assert row["lead_vs_baseline_h"] <= 0.0

    healthy, _ = make_mock("S2")  # level never low: nothing to count
    row2 = lead_times(alerts, gt, healthy, TH).iloc[0]
    assert row2["baseline_ts"] is None and math.isnan(row2["lead_vs_baseline_h"])


def test_through_fault_has_no_baseline():
    trend, _ = make_mock("S5")
    alerts = [make_alert(_t(27, 10.5), "through_fault", "critical", "physics")]
    row = lead_times(alerts, ground_truth("S5"), trend, TH).iloc[0]
    assert row["detected"] and row["baseline_rule"] is None and row["baseline_ts"] is None
    assert math.isnan(row["lead_vs_baseline_h"])


def test_one_row_per_fault_and_empty_ground_truth():
    trend, _ = make_mock("S4")
    assert len(lead_times([], ground_truth("S4"), trend, TH)) == 2
    assert lead_times([], [], trend, TH).empty
