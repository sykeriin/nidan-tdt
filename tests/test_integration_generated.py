"""P3 analytics on the team's real pipeline: ingest adapter -> P2 generator output -> twin engine -> analyze().

Uses the committed data/generated scenario files, so no mock data is involved. Ground truth (gt_*) is read only
to say which alert types each scenario should raise, never passed to a detector.
"""
import warnings
from collections import Counter

import pytest

from analytics import residual
from analytics.common import load_thresholds
from analytics.pipeline import analyze
from ingest import adapter
from twin.engine import TwinEngine

T = load_thresholds()
SCENARIOS = ("N", "S1", "S2", "S3", "S4a", "S4b", "S5")
EXPECT = {
    "S1": {"loading_high", "hot_spot_high"},
    "S2": {"residual_drift"},
    "S3": {"current_unbalance"},
    "S4a": {"oil_leak"},
    "S4b": {"oil_theft"},
    "S5": {"through_fault", "through_fault_stress"},
}


@pytest.fixture(scope="module")
def results():
    warnings.simplefilter("ignore")
    twins, evs, caps = {}, {}, {}
    for s in SCENARIOS:
        ds = adapter.load([f"data/generated/trend_{s}.csv", f"data/generated/events_{s}.csv"])
        twins[s], evs[s], caps[s] = TwinEngine().run(ds), ds.events, ds.capabilities
    ref = residual.calibrate(twins["N"], T)
    return {s: analyze(twins[s], evs[s], caps[s], T, residual_reference=ref) for s in SCENARIOS}


def test_normal_raises_no_alerts(results):
    assert results["N"].alerts == []


@pytest.mark.parametrize("s", sorted(EXPECT))
def test_each_fault_raises_its_alert(results, s):
    types = {a.type for a in results[s].alerts if a.origin == "asset"}
    assert EXPECT[s] & types, f"{s}: expected one of {EXPECT[s]}, got {sorted(types)}"


def test_overload_is_not_called_a_sensor_fault(results):
    """A real overload moves the hot spot fast; the twin predicts it, so it must stay an asset alert."""
    assert [a for a in results["S1"].alerts if a.origin == "sensor"] == []


def test_no_scenario_raises_sensor_alerts_on_clean_generated_data(results):
    c = Counter(a.type for r in results.values() for a in r.alerts if a.origin == "sensor")
    assert not c, dict(c)


def test_cooling_fault_is_flagged_by_the_residual_first(results):
    first = {a.type: a.timestamp for a in results["S2"].alerts}
    assert "residual_drift" in first
    assert first["residual_drift"] < min(t for k, t in first.items() if k in ("top_oil_high", "hot_spot_high"))
