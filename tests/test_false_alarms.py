"""Unit tests for eval.false_alarms with hand-built alerts."""
from __future__ import annotations

import pandas as pd
import pytest

from analytics.common import make_alert
from eval.false_alarms import false_alarms
from eval.scenarios import START, ground_truth


def _t(days: float = 0, hours: float = 0) -> pd.Timestamp:
    return START + pd.Timedelta(days=days, hours=hours)


def test_no_alerts():
    r = false_alarms([], [])
    assert r == {"count": 0, "by_type": {}, "alerts_per_week": 0.0, "true_positive_count": 0}


def test_normal_every_warning_and_critical_is_false():
    alerts = [
        make_alert(_t(3), "loading_high", "warning", "rule"),
        make_alert(_t(4), "loading_high", "critical", "rule"),
        make_alert(_t(5), "oil_low", "warning", "rule"),
    ]
    r = false_alarms(alerts, ground_truth("N"))
    assert r["count"] == 3 and r["true_positive_count"] == 0
    assert r["by_type"] == {"loading_high": 2, "oil_low": 1}


def test_info_alerts_are_ignored():
    alerts = [make_alert(_t(3), "ageing_rate_high", "info", "rule"), make_alert(_t(3), "loading_high", "info", "rule")]
    r = false_alarms(alerts, [])
    assert r["count"] == 0 and r["true_positive_count"] == 0


def test_true_positive_vs_false_alarm_on_fault_scenario():
    gt = ground_truth("S1")
    alerts = [
        make_alert(_t(25), "loading_high", "warning", "rule"),  # in window, expected type
        make_alert(_t(25), "voltage_low", "warning", "rule"),  # in window, wrong type
        make_alert(_t(10), "loading_high", "warning", "rule"),  # right type, before onset
        make_alert(pd.Timestamp("2026-04-27 10:00", tz="Asia/Kolkata"), "hot_spot_high", "critical", "rule"),  # inside the 24 h grace after end (S1 ends 04-26 13:45)
    ]
    r = false_alarms(alerts, gt)
    assert r["true_positive_count"] == 2
    assert r["count"] == 2
    assert r["by_type"] == {"voltage_low": 1, "loading_high": 1}


def test_alert_after_grace_is_false():
    r = false_alarms([make_alert(_t(28, 1), "loading_high", "warning", "rule")], ground_truth("S1"))
    assert r["count"] == 1


def test_alerts_per_week_uses_days():
    alerts = [make_alert(_t(i), "voltage_high", "warning", "rule") for i in range(3)]
    assert false_alarms(alerts, [], days=30)["alerts_per_week"] == pytest.approx(3 / (30 / 7))
    assert false_alarms(alerts, [], days=7)["alerts_per_week"] == pytest.approx(3.0)
    assert false_alarms(alerts, [])["alerts_per_week"] == pytest.approx(0.7)
