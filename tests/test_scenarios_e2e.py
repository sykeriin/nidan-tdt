"""End-to-end scenario expectations through analyze(). Fail until the detectors (Agents A and B) are merged."""
from __future__ import annotations

import dataclasses
import inspect

import pandas as pd
import pytest

from analytics import residual
from analytics.common import load_thresholds, strip_quarantined
from analytics.pipeline import analyze
from eval.lead_time import alert_matches_fault, baseline_crossings
from tests.mock_data import SCENARIOS, ground_truth, make_mock, mock_caps

TH = load_thresholds()


def _run(sc: str):
    trend, events = make_mock(sc)
    kwargs = {}
    if "residual_reference" in inspect.signature(analyze).parameters:
        normal, _ = make_mock("N")
        kwargs["residual_reference"] = residual.calibrate(strip_quarantined(normal), TH)
    return trend, analyze(trend, events, mock_caps(), TH, **kwargs).alerts


@pytest.fixture(scope="module")
def results():
    return {sc: _run(sc) for sc in SCENARIOS}


def test_normal_has_no_warning_or_critical(results):
    _, alerts = results["N"]
    bad = [(a.type, a.severity) for a in alerts if a.severity in ("warning", "critical")]
    assert bad == []


@pytest.mark.parametrize("sc", ["S1", "S2", "S3", "S4", "S5"])
def test_each_fault_alerts_inside_its_window(sc, results):
    _, alerts = results[sc]
    for fault in ground_truth(sc):
        hits = [a for a in alerts if alert_matches_fault(a, fault)]
        assert hits, f"{sc}: no {fault['expect']} alert for {fault['fault']}"


def test_s2_residual_drift_precedes_top_oil_baseline(results):
    trend, alerts = results["S2"]
    drift = [a for a in alerts if a.type == "residual_drift"]
    assert drift, "no residual_drift alert"
    top_oil = baseline_crossings(trend, TH)["top_oil_warning"]
    assert top_oil is None  # in the mock OTI_C never reaches the top-oil warning
    assert min(pd.Timestamp(a.timestamp) for a in drift) >= ground_truth("S2")[0]["onset"]


def test_s5_through_fault_alerts_come_from_event_table(results):
    _, alerts = results["S5"]
    _, events = make_mock("S5")
    tf = [a for a in alerts if a.type in ("through_fault", "through_fault_stress")]
    assert tf, "no through-fault alerts"
    event_times = set(pd.to_datetime(events["timestamp"]))
    assert any(pd.Timestamp(a.timestamp) in event_times for a in tf if a.type == "through_fault")


def test_every_alert_is_simulated(results):
    for sc, (_, alerts) in results.items():
        assert all(a.simulated is True for a in alerts), sc


def test_no_alert_references_gt_columns(results):
    for sc, (trend, alerts) in results.items():
        gt_cols = [c for c in trend.columns if c.startswith(("gt_", "alarm_"))]
        for a in alerts:
            text = " ".join(str(v) for v in dataclasses.asdict(a).values())
            assert not any(c in text for c in gt_cols), (sc, a.id)
            assert "gt_" not in text and "ground truth" not in text.lower(), (sc, a.id)
