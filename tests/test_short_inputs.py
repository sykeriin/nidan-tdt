"""Detectors must not crash on 0 or 1 rows (StreamAnalyzer feeds one row at a time)."""
import pytest

from analytics import electrical, oil, residual, rules, through_fault
from analytics.common import load_thresholds
from tests.mock_data import make_mock, mock_caps

T = load_thresholds()


@pytest.mark.parametrize("rows", [0, 1])
def test_trend_detectors_return_empty_on_short_input(rows):
    trend, _ = make_mock("S1", days=3)
    df = trend.iloc[:rows]
    assert rules.detect(df, T) == []
    assert residual.detect(df, T) == []
    assert oil.detect(df, T) == []
    assert electrical.detect(df, T, mock_caps()) == []


def test_through_fault_handles_empty_events():
    _, ev = make_mock("N", days=3)
    assert through_fault.detect(ev, T) == []
