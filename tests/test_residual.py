import numpy as np
import pandas as pd

from analytics import residual, rules
from analytics.common import load_thresholds
from tests.mock_data import ground_truth, make_mock

TH = load_thresholds()


def test_calibrate_matches_trip_formula():
    trend, _ = make_mock("N")
    ref = residual.calibrate(trend, TH)
    assert ref["trip"] == ref["mean"] + TH["operating"]["residual"]["sigma_mult"] * ref["sigma"]
    assert ref["sigma"] > 0


def test_normal_no_alerts_with_reference_and_self_referenced():
    trend, _ = make_mock("N")
    assert residual.detect(trend, TH, residual.calibrate(trend, TH)) == []
    assert residual.detect(trend, TH) == []


def test_cooling_degradation_detected_before_top_oil_warning():
    normal, _ = make_mock("N")
    ref = residual.calibrate(normal, TH)
    trend, _ = make_mock("S2")
    alerts = residual.detect(trend, TH, ref)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.type == "residual_drift" and a.detector == "residual" and a.simulated
    onset = ground_truth("S2")[0]["onset"]
    assert a.timestamp >= onset
    oti_warn = TH["operating"]["top_oil_c"]["warning"]
    assert trend.loc[trend.timestamp <= a.timestamp, "OTI_C"].max() < oti_warn
    assert rules.detect(trend, TH) == [] or all(x.type != "top_oil_high" for x in rules.detect(trend, TH))


def test_self_referenced_fallback_detects_and_says_so():
    trend, _ = make_mock("S2")
    alerts = residual.detect(trend, TH)
    assert len(alerts) == 1
    assert "self-referenced baseline" in alerts[0].explanation


def test_reference_explanation_has_no_self_reference_wording():
    normal, _ = make_mock("N")
    trend, _ = make_mock("S2")
    a = residual.detect(trend, TH, residual.calibrate(normal, TH))[0]
    assert "self-referenced" not in a.explanation


def test_meter_only_returns_empty():
    trend, _ = make_mock("S2")
    trend["residual_oil_C"] = np.nan
    assert residual.detect(trend, TH) == []
    assert residual.calibrate(trend, TH) == {}
    assert residual.detect(trend.drop(columns=["residual_oil_C"]), TH) == []


def test_single_spike_is_not_persistent():
    trend, _ = make_mock("N")
    ref = residual.calibrate(trend, TH)
    trend.loc[500, "residual_oil_C"] = ref["trip"] + 4.0 * 0.4 * 2
    assert residual.detect(trend, TH, ref) == []


def test_one_alert_when_drift_dips_under_trip_overnight():
    trend, _ = make_mock("S2")
    assert len(residual.detect(trend, TH)) == 1
