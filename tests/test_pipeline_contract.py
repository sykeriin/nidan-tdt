import pandas as pd
import pytest

from analytics import electrical, oil, pipeline, residual, rules, through_fault
from analytics.common import load_thresholds, make_alert
from contracts.models import AnalysisResult, TwinState
from tests.mock_data import make_mock, mock_caps

TH = load_thresholds()
TWIN_COLS = ["twin_oil_C", "twin_hs_C", "aging_rate", "days_aged_cum", "residual_oil_C", "fidelity_rmse_C", "load_pu"]


def _stub_all(monkeypatch):
    monkeypatch.setattr(rules, "detect", lambda df, th: [])
    monkeypatch.setattr(residual, "detect", lambda df, th, reference=None: [])
    monkeypatch.setattr(electrical, "detect", lambda df, th, caps: [])
    monkeypatch.setattr(oil, "detect", lambda df, th: [])
    monkeypatch.setattr(through_fault, "detect", lambda ev, th: [])


def test_valid_result_with_empty_detectors(monkeypatch):
    _stub_all(monkeypatch)
    df, ev = make_mock("N", days=3)
    res = pipeline.analyze(df, ev, mock_caps(), TH)
    assert isinstance(res, AnalysisResult)
    assert res.alerts == [] and res.recommendations == [] and res.rul is None
    assert res.health.band == "Green" and 0 <= res.health.score <= 100
    assert res.fidelity_rmse_C == pytest.approx(df.fidelity_rmse_C.dropna().iloc[-1])


def test_quarantined_columns_never_reach_detectors(monkeypatch):
    seen = []

    def spy(*args, **kwargs):
        seen.extend(c for a in args if isinstance(a, pd.DataFrame) for c in a.columns)
        return []

    for mod in (rules, residual, electrical, oil, through_fault):
        monkeypatch.setattr(mod, "detect", spy)
    df, ev = make_mock("S5", days=3)
    df = df.assign(alarm_oti=1)
    ev = ev.assign(gt_x=1, alarm_y=2)
    assert "gt_fault" in df.columns
    pipeline.analyze(df, ev, mock_caps(), TH)
    assert seen and not any(c.startswith(("gt_", "alarm_")) for c in seen)


def test_alerts_sorted_and_recommended(monkeypatch):
    _stub_all(monkeypatch)
    t = pd.Timestamp("2026-04-02 10:00", tz="Asia/Kolkata")
    late = make_alert(t + pd.Timedelta(hours=3), "oil_low", "warning", "rule")
    early = make_alert(t, "hot_spot_high", "critical", "rule", value=125.0, threshold=120.0)
    monkeypatch.setattr(rules, "detect", lambda df, th: [late])
    monkeypatch.setattr(oil, "detect", lambda df, th: [early])
    df, ev = make_mock("N", days=3)
    res = pipeline.analyze(df, ev, mock_caps(), TH)
    assert [a.type for a in res.alerts] == ["hot_spot_high", "oil_low"]
    assert all(a.recommendation_id for a in res.alerts)
    assert {r.alert_id for r in res.recommendations} == {a.id for a in res.alerts}


def test_residual_reference_is_forwarded(monkeypatch):
    _stub_all(monkeypatch)
    got = {}

    def spy(df, th, reference=None):
        got["ref"] = reference
        return []

    monkeypatch.setattr(residual, "detect", spy)
    df, ev = make_mock("N", days=3)
    pipeline.analyze(df, ev, mock_caps(), TH, residual_reference={"mean": 0.1})
    assert got["ref"] == {"mean": 0.1}


@pytest.mark.parametrize("scenario", ["N", "S5"])
def test_stream_analyzer_equals_batch(scenario):
    df, ev = make_mock(scenario, days=3)
    if scenario == "S5":  # mock events sit on day 27, so move them inside the 3-day window
        ev = ev.assign(timestamp=df.timestamp.iloc[[100, 150, 200]].to_numpy())
    sa = pipeline.StreamAnalyzer(mock_caps(), TH)
    records = ev.to_dict("records")
    last = None
    for _, row in df.iterrows():
        d = row.to_dict()
        ts = d["timestamp"]
        twin = {k: d.pop(k) for k in TWIN_COLS}
        new = [e for e in records if e["timestamp"] == ts]
        last = sa.update(TwinState(timestamp=ts, row=d, twin=twin, mode="full"), new)
    assert last == pipeline.analyze(df, ev, mock_caps(), TH)
