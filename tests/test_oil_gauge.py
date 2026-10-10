"""Theft needs a step that persists and does not recover. Gauge dips and thermal swings must not alert."""
import numpy as np
import pytest

from analytics import oil
from analytics.common import load_thresholds
from eval.scenarios import kaggle, load_scenario

T = load_thresholds()


def _flat(days=3):
    t, _ = load_scenario("N", days=days)
    t = t.copy()
    t["OLI_pct"] = 100.0
    return t


def _theft(df):
    return [a for a in oil.detect(df, T) if a.type == "oil_theft"]


def test_one_sample_dip_is_not_theft():
    t = _flat()
    t.loc[100, "OLI_pct"] = 90.0  # 10-point dip, back next sample
    assert _theft(t) == []


def test_drop_that_recovers_within_a_day_is_not_theft():
    t = _flat()
    t.loc[100:109, "OLI_pct"] = 88.0  # down 12 points for 2.5 h, then back to 100
    assert _theft(t) == []


def test_persistent_drop_is_theft():
    t = _flat()
    t.loc[100:, "OLI_pct"] = 88.0
    a = _theft(t)
    assert len(a) == 1 and a[0].timestamp == t["timestamp"].iloc[100]


def test_drop_too_close_to_end_of_data_cannot_be_confirmed():
    t = _flat()
    t.loc[len(t) - 2 :, "OLI_pct"] = 88.0  # only 1 sample after the step, less than the persistence window
    assert _theft(t) == []


def test_generated_theft_still_detected():
    t, _ = load_scenario("S4b")
    assert len(_theft(t)) == 1


def test_real_kaggle_gauge_swings_raise_no_theft_alerts():
    df, _ = kaggle()
    assert _theft(df) == []  # every persistent drop in this data recovers within 24 h
