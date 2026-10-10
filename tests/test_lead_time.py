"""Unit tests for eval.lead_time with hand-built alerts on the real generated scenarios (eval/scenarios.py)."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from analytics.common import load_thresholds, make_alert
from eval.lead_time import baseline_crossings, lead_times
from eval.scenarios import START, ground_truth, load_scenario

TH = load_thresholds()


def _t(days: float = 0, hours: float = 0) -> pd.Timestamp:
    return START + pd.Timedelta(days=days, hours=hours)


def ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="Asia/Kolkata")


def test_baseline_never_fires_on_normal_and_s5():
    for sc in ("N", "S5"):
        trend, _ = load_scenario(sc)
        assert all(v is None for v in baseline_crossings(trend, TH).values()), sc


def test_s2_baseline_fires_only_a_week_after_onset():
    c = baseline_crossings(load_scenario("S2")[0], TH)
    assert c["top_oil_warning"] == ts("2026-04-27 15:00")       # onset 2026-04-20 00:00
    assert c["hot_spot_warning"] == ts("2026-04-27 14:00")


def test_baseline_s1_crossings():
    trend, _ = load_scenario("S1")
    c = baseline_crossings(trend, TH)
    assert c["loading_alarm"] == ts("2026-04-24 12:00")   # overload window opens 11:30, load ramps to 1.10 pu
    assert c["overcurrent"] is not None and c["overcurrent"] >= c["loading_alarm"]
    assert c["unbalance_warning"] is None and c["oil_level_low"] is None


def test_baseline_ignores_gt_columns():
    trend, _ = load_scenario("S1")
    base = baseline_crossings(trend, TH)
    scrambled = trend.copy()
    scrambled["gt_fault"] = "x"
    assert baseline_crossings(scrambled, TH) == base


def test_baseline_since_filters_earlier_samples():
    trend, _ = load_scenario("S4a")
    assert baseline_crossings(trend, TH)["oil_level_low"] == ts("2026-04-23 22:00")
    later = ts("2026-04-27 02:30")                              # level is still low then: first sample counted
    assert baseline_crossings(trend, TH, since=later)["oil_level_low"] == later


def test_detected_fault_with_baseline_lead():
    trend, _ = load_scenario("S1")
    gt = ground_truth("S1")
    alerts = [make_alert(ts("2026-04-24 12:30"), "loading_high", "warning", "rule")]
    row = lead_times(alerts, gt, trend, TH).iloc[0]
    assert row["detected"] and row["fault"] == "overload"
    assert row["first_alert_type"] == "loading_high" and row["detector"] == "rule"
    assert row["baseline_rule"] == "loading_alarm" and row["baseline_ts"] == ts("2026-04-24 12:00")
    assert row["lead_vs_baseline_h"] == pytest.approx(-0.5)
    assert row["lead_vs_onset_h"] == pytest.approx(-1.0)


def test_undetected_fault_has_nan_leads():
    trend, _ = load_scenario("S1")
    row = lead_times([], ground_truth("S1"), trend, TH).iloc[0]
    assert not row["detected"] and row["first_alert_ts"] is None and row["detector"] is None
    assert math.isnan(row["lead_vs_baseline_h"]) and math.isnan(row["lead_vs_onset_h"])


def test_alert_outside_window_or_wrong_type_does_not_match():
    trend, _ = load_scenario("S1")
    gt = ground_truth("S1")
    alerts = [
        make_alert(ts("2026-04-24 08:00"), "loading_high", "warning", "rule"),  # before onset
        make_alert(ts("2026-04-25 12:00"), "oil_low", "warning", "rule"),  # wrong type
        make_alert(ts("2026-04-27 14:00"), "loading_high", "warning", "rule"),  # beyond end + 24 h
    ]
    assert not lead_times(alerts, gt, trend, TH).iloc[0]["detected"]


def test_baseline_never_fires_gives_nan_lead_and_none_ts():
    trend, _ = load_scenario("S2")
    trend = trend[trend["timestamp"] < ts("2026-04-27")]          # cut before the 85 C crossing
    alerts = [make_alert(ts("2026-04-22 00:00"), "residual_drift", "warning", "residual")]
    row = lead_times(alerts, ground_truth("S2"), trend, TH).iloc[0]
    assert row["detected"] and row["baseline_ts"] is None
    assert math.isnan(row["lead_vs_baseline_h"])
    assert "never crossed" in row["baseline_rule"]
    assert row["lead_vs_onset_h"] == pytest.approx(-48.0)


def test_late_detection_is_negative_vs_onset_and_early_is_positive_vs_baseline():
    trend, _ = load_scenario("S4a")
    gt = ground_truth("S4a")                                      # onset 2026-04-21 06:00
    alerts = [make_alert(ts("2026-04-22 06:00"), "oil_leak", "warning", "rule")]
    row = lead_times(alerts, gt, trend, TH).iloc[0]
    assert row["lead_vs_onset_h"] == pytest.approx(-24.0)
    assert row["baseline_ts"] == ts("2026-04-23 22:00")
    assert row["lead_vs_baseline_h"] == pytest.approx(40.0)


def test_theft_baseline_counts_only_at_or_after_onset():
    trend, _ = load_scenario("S4b")
    gt = ground_truth("S4b")
    alerts = [make_alert(ts("2026-04-25 02:30"), "oil_theft", "critical", "rule")]
    row = lead_times(alerts, gt, trend, TH).iloc[0]
    assert row["baseline_rule"] == "oil_level_low"
    assert row["baseline_ts"] >= gt[0]["onset"]
    assert row["lead_vs_baseline_h"] <= 0.0

    healthy, _ = load_scenario("S2")  # level never low: nothing to count
    row2 = lead_times(alerts, gt, healthy, TH).iloc[0]
    assert row2["baseline_ts"] is None and math.isnan(row2["lead_vs_baseline_h"])


def test_through_fault_has_no_baseline():
    trend, _ = load_scenario("S5")
    alerts = [make_alert(ts("2026-04-27 10:30"), "through_fault", "critical", "physics")]
    row = lead_times(alerts, ground_truth("S5"), trend, TH).iloc[0]
    assert row["detected"] and row["baseline_rule"] is None and row["baseline_ts"] is None
    assert math.isnan(row["lead_vs_baseline_h"])


def test_one_row_per_fault_and_empty_ground_truth():
    trend, _ = load_scenario("S4a")
    two = ground_truth("S4a") + ground_truth("S4b")
    assert len(lead_times([], two, trend, TH)) == 2
    assert lead_times([], [], trend, TH).empty
