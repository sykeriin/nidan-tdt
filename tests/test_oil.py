import numpy as np
import pandas as pd

from analytics import oil
from analytics.common import load_thresholds
from eval.scenarios import ground_truth, load_scenario

TH = load_thresholds()
SEVERE = {"warning", "critical"}


def _by_type(alerts, t):
    return [a for a in alerts if a.type == t]


def test_normal_has_no_alerts():
    trend, _ = load_scenario("N")
    assert [a for a in oil.detect(trend, TH) if a.severity in SEVERE] == []


THEFT_AT = pd.Timestamp("2026-04-25 02:15", tz="Asia/Kolkata")   # S4b step (config/scenarios.yaml)


def test_leak_in_s4a_is_one_leak_then_low():
    trend, _ = load_scenario("S4a")
    alerts = oil.detect(trend, TH)
    leak, low, theft = _by_type(alerts, "oil_leak"), _by_type(alerts, "oil_low"), _by_type(alerts, "oil_theft")
    assert len(leak) == 1 and len(low) == 1 and theft == []      # one slow leak, never read as theft
    g = ground_truth("S4a")[0]
    assert g["onset"] <= leak[0].timestamp <= g["end"]
    assert leak[0].timestamp < low[0].timestamp                   # slope detector beats the level threshold


def test_theft_in_s4b_is_critical_night_step():
    trend, _ = load_scenario("S4b")
    alerts = oil.detect(trend, TH)
    theft, leak = _by_type(alerts, "oil_theft"), _by_type(alerts, "oil_leak")
    assert len(theft) == 1 and leak == []                         # a step is not a leak
    assert theft[0].severity == "critical"
    assert THEFT_AT <= theft[0].timestamp <= THEFT_AT + pd.Timedelta(hours=1)
    assert "night" in theft[0].explanation


def _move_step(trend, new_time):
    """Same 12-point step, moved from 02:15 to new_time on the same day."""
    t = trend.copy()
    step = float(t.loc[t.timestamp < THEFT_AT, "OLI_pct"].iloc[-1] - t.loc[t.timestamp >= THEFT_AT + pd.Timedelta(hours=1), "OLI_pct"].iloc[0])
    between = (t.timestamp >= THEFT_AT) & (t.timestamp < new_time)
    t.loc[between, "OLI_pct"] += round(step)
    return t


def test_daytime_theft_has_no_night_flag():
    trend, _ = load_scenario("S4b")
    theft = _by_type(oil.detect(_move_step(trend, pd.Timestamp("2026-04-25 14:00", tz="Asia/Kolkata")), TH), "oil_theft")
    assert theft and "night" not in theft[-1].explanation


def test_thermal_cause_suppresses_theft():
    trend, _ = load_scenario("S4b")
    hot = trend.copy()
    hot.loc[hot.timestamp >= THEFT_AT, "OTI_C"] -= 15.0         # oil cooled sharply at the same moment: contraction
    assert _by_type(oil.detect(hot, TH), "oil_theft") == []


def test_theft_without_temperature_channels_still_reported():
    trend, _ = load_scenario("S4b")
    bare = trend.drop(columns=["OTI_C", "twin_oil_C"])
    theft = _by_type(oil.detect(bare, TH), "oil_theft")
    assert len(theft) == 1 and "no temperature channel" in theft[0].explanation


def test_noise_around_low_level_does_not_chatter():
    ts = pd.date_range("2026-01-01", periods=12, freq="15min", tz="Asia/Kolkata")
    lvl = [90, 84.9, 85.2, 84.8, 85.3, 84.9, 85.4, 84.7, 85.1, 90, 90, 90]
    df = pd.DataFrame({"timestamp": ts, "OLI_pct": lvl, "simulated": True})
    assert len(_by_type(oil.detect(df, TH), "oil_low")) == 1


def test_missing_or_nan_level_returns_empty():
    trend, _ = load_scenario("S4a")
    assert oil.detect(trend.drop(columns=["OLI_pct"]), TH) == []
    nan = trend.copy()
    nan["OLI_pct"] = np.nan
    assert oil.detect(nan, TH) == []
    assert oil.detect(trend.iloc[0:0], TH) == []
