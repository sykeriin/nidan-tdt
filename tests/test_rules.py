import numpy as np
import pandas as pd

from analytics import rules
from analytics.common import load_thresholds
from tests.mock_data import ground_truth, make_mock

TH = load_thresholds()
SEVERE = {"warning", "critical"}


def _types(alerts):
    return {a.type for a in alerts}


def _small(values, col="load_pu"):
    ts = pd.date_range("2026-01-01", periods=len(values), freq="15min", tz="Asia/Kolkata")
    return pd.DataFrame({"timestamp": ts, col: values, "simulated": True})


def test_normal_has_no_alerts():
    trend, _ = make_mock("N")
    assert [a for a in rules.detect(trend, TH) if a.severity in SEVERE] == []


def test_overload_scenario_alert_types_and_onset():
    trend, _ = make_mock("S1")
    alerts = rules.detect(trend, TH)
    assert {"loading_high", "overcurrent", "hot_spot_high", "top_oil_high"} <= _types(alerts)
    onset = ground_truth("S1")[0]["onset"]
    first = min(a.timestamp for a in alerts if a.type == "loading_high")
    assert onset <= first <= onset + pd.Timedelta(hours=2)
    assert all(a.simulated and a.detector == "rule" for a in alerts)


def test_one_alert_per_episode():
    trend, _ = make_mock("S1")
    alerts = rules.detect(trend, TH)
    overload_days = [a for a in alerts if a.type == "overcurrent"]
    assert len(overload_days) == 3  # one per overloaded day, not one per sample


def test_hysteresis_does_not_chatter():
    # hovers around the 0.9 warning level but never clears below 0.855
    vals = [0.5, 0.91, 0.89, 0.91, 0.88, 0.92, 0.87, 0.9, 0.5]
    alerts = [a for a in rules.detect(_small(vals), TH) if a.type == "loading_high"]
    assert len(alerts) == 1
    assert alerts[0].timestamp == _small(vals)["timestamp"].iloc[1]
    vals2 = vals + [0.5, 0.95, 0.5]
    assert len([a for a in rules.detect(_small(vals2), TH) if a.type == "loading_high"]) == 2


def test_escalation_raises_second_alert():
    alerts = [a for a in rules.detect(_small([0.5, 0.95, 1.05, 0.5]), TH) if a.type == "loading_high"]
    assert [a.severity for a in alerts] == ["warning", "critical"]


def test_loading_pct_fallback():
    df = _small([50.0, 95.0, 50.0], col="loading_pct")
    assert [a.type for a in rules.detect(df, TH)] == ["loading_high"]


def test_meter_only_uses_twin_and_says_so():
    trend, _ = make_mock("S1")
    meter = trend.drop(columns=["OTI_C", "WTI_C"])
    alerts = rules.detect(meter, TH)
    assert {"top_oil_high", "hot_spot_high"} <= _types(alerts)
    for a in alerts:
        if a.type in ("top_oil_high", "hot_spot_high"):
            assert "twin-estimated" in a.explanation
    measured = rules.detect(trend, TH)
    assert all("measured" in a.explanation for a in measured if a.type in ("top_oil_high", "hot_spot_high"))


def test_all_nan_oti_falls_back_to_twin():
    trend, _ = make_mock("S1")
    trend["OTI_C"] = np.nan
    alerts = [a for a in rules.detect(trend, TH) if a.type == "top_oil_high"]
    assert alerts and "twin-estimated" in alerts[0].explanation


def test_missing_channels_return_empty_and_never_crash():
    df = pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=5, freq="15min")})
    assert rules.detect(df, TH) == []
    assert rules.detect(df.iloc[0:0], TH) == []


def test_quarantined_columns_are_ignored():
    trend, _ = make_mock("N")
    trend["alarm_hot"] = 1000.0
    trend["gt_load_pu"] = 5.0
    assert [a for a in rules.detect(trend, TH) if a.severity in SEVERE] == []
