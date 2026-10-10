"""Detectors must not crash on 0 or 1 rows (StreamAnalyzer feeds one row at a time)."""
import pytest

from analytics import electrical, oil, residual, rules, through_fault
from analytics.common import load_thresholds
from eval.scenarios import load_scenario, capabilities

T = load_thresholds()


@pytest.mark.parametrize("rows", [0, 1])
def test_trend_detectors_return_empty_on_short_input(rows):
    trend, _ = load_scenario("S1", days=3)
    df = trend.iloc[:rows]
    assert rules.detect(df, T) == []
    assert residual.detect(df, T) == []
    assert oil.detect(df, T) == []
    assert electrical.detect(df, T, capabilities()) == []


def test_through_fault_handles_empty_events():
    _, ev = load_scenario("N", days=3)
    assert through_fault.detect(ev, T) == []
