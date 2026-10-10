import numpy as np
import pandas as pd
import pytest

from analytics.common import (
    ALERT_MODULES, hysteresis_mask, load_thresholds, make_alert, persistent_mask, runs, step_hours, strip_quarantined,
)


def test_load_thresholds_has_expected_blocks():
    t = load_thresholds()
    assert {"operating", "reference", "bench"} <= set(t)
    assert t["operating"]["top_oil_c"]["critical"] == 95
    assert t["bench"]["temperature_trip_c"] == 60  # bench value, never an operating alarm


def test_strip_quarantined_removes_gt_and_alarm():
    df = pd.DataFrame({"a": [1], "gt_fault": ["x"], "alarm_oti": [1], "gt_other": [2]})
    assert list(strip_quarantined(df).columns) == ["a"]


def test_hysteresis_high_holds_until_clear_margin():
    v = np.array([0.5, 1.0, 0.97, 0.96, 0.94, 0.5])
    m = hysteresis_mask(v, trip=1.0, clear_fraction=0.95, direction="high")
    assert m.tolist() == [False, True, True, True, False, False]


def test_hysteresis_low_direction():
    v = np.array([100, 85, 88, 92, 100])
    m = hysteresis_mask(v, trip=85, clear_fraction=0.95, direction="low")
    assert m[1] and m[2] and not m[4]


def test_hysteresis_nan_keeps_state():
    m = hysteresis_mask(np.array([1.2, np.nan, np.nan, 0.5]), trip=1.0)
    assert m.tolist() == [True, True, True, False]


def test_persistent_mask_drops_short_runs():
    m = np.array([1, 1, 0, 1, 1, 1, 0], dtype=bool)
    assert persistent_mask(m, 3).tolist() == [False, False, False, True, True, True, False]


def test_runs():
    assert runs(np.array([0, 1, 1, 0, 1], dtype=bool)) == [(1, 2), (4, 4)]
    assert runs(np.zeros(3, dtype=bool)) == []


def test_make_alert_deterministic_id_and_unknown_type():
    a = make_alert(pd.Timestamp("2026-04-20 10:15"), "oil_leak", "warning", "rule", value=80, threshold=85)
    assert a.id == "oil_leak-20260420T1015" and a.module == "oil" and a.origin == "asset"
    with pytest.raises(ValueError):
        make_alert(pd.Timestamp("2026-04-20"), "not_a_type", "info", "rule")


def test_step_hours():
    df = pd.DataFrame({"timestamp": pd.date_range("2026-04-01", periods=5, freq="15min")})
    assert step_hours(df) == 0.25


def test_every_alert_type_has_a_module():
    assert all(ALERT_MODULES.values())
