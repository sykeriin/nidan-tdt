import numpy as np
import pandas as pd

from analytics import oil
from analytics.common import load_thresholds
from tests.mock_data import ground_truth, make_mock

TH = load_thresholds()
SEVERE = {"warning", "critical"}


def _by_type(alerts, t):
    return [a for a in alerts if a.type == t]


def test_normal_has_no_alerts():
    trend, _ = make_mock("N")
    assert [a for a in oil.detect(trend, TH) if a.severity in SEVERE] == []


def test_leak_low_and_theft_in_s4():
    trend, _ = make_mock("S4")
    alerts = oil.detect(trend, TH)
    leak, low, theft = _by_type(alerts, "oil_leak"), _by_type(alerts, "oil_low"), _by_type(alerts, "oil_theft")
    assert len(leak) == 1 and len(low) == 1 and len(theft) == 1
    truth = {g["fault"]: g for g in ground_truth("S4")}
    assert truth["oil_leak"]["onset"] <= leak[0].timestamp <= truth["oil_leak"]["end"]
    assert leak[0].timestamp < low[0].timestamp
    assert theft[0].severity == "critical"
    onset = truth["oil_theft"]["onset"]
    assert onset <= theft[0].timestamp <= onset + pd.Timedelta(hours=1)
    assert "night" in theft[0].explanation
    assert theft[0].timestamp > leak[0].timestamp


def test_leak_is_not_misread_as_theft_and_theft_not_as_leak_again():
    trend, _ = make_mock("S4")
    alerts = oil.detect(trend, TH)
    theft_ts = _by_type(alerts, "oil_theft")[0].timestamp
    assert all(a.timestamp < theft_ts for a in _by_type(alerts, "oil_leak"))


def test_daytime_theft_has_no_night_flag():
    trend, _ = make_mock("S4")
    shift = trend.copy()
    at = shift.timestamp >= pd.Timestamp("2026-04-28 13:00", tz="Asia/Kolkata")
    shift.loc[at, "OLI_pct"] = shift.loc[at, "OLI_pct"] + 12.0  # undo the 02:30 step
    shift.loc[shift.timestamp >= pd.Timestamp("2026-04-28 14:00", tz="Asia/Kolkata"), "OLI_pct"] -= 12.0
    theft = _by_type(oil.detect(shift, TH), "oil_theft")
    assert theft and "night" not in theft[-1].explanation


def test_thermal_cause_suppresses_theft():
    trend, _ = make_mock("S4")
    t = pd.Timestamp("2026-04-28 02:30", tz="Asia/Kolkata")
    hot = trend.copy()
    hot.loc[hot.timestamp >= t, "OTI_C"] -= 15.0
    assert _by_type(oil.detect(hot, TH), "oil_theft") == []


def test_theft_without_temperature_channels_still_reported():
    trend, _ = make_mock("S4")
    bare = trend.drop(columns=["OTI_C", "twin_oil_C"])
    theft = _by_type(oil.detect(bare, TH), "oil_theft")
    assert len(theft) == 1 and "no temperature channel" in theft[0].explanation


def test_noise_around_low_level_does_not_chatter():
    ts = pd.date_range("2026-01-01", periods=12, freq="15min", tz="Asia/Kolkata")
    lvl = [90, 84.9, 85.2, 84.8, 85.3, 84.9, 85.4, 84.7, 85.1, 90, 90, 90]
    df = pd.DataFrame({"timestamp": ts, "OLI_pct": lvl, "simulated": True})
    assert len(_by_type(oil.detect(df, TH), "oil_low")) == 1


def test_missing_or_nan_level_returns_empty():
    trend, _ = make_mock("S4")
    assert oil.detect(trend.drop(columns=["OLI_pct"]), TH) == []
    nan = trend.copy()
    nan["OLI_pct"] = np.nan
    assert oil.detect(nan, TH) == []
    assert oil.detect(trend.iloc[0:0], TH) == []
