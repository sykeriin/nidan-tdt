import numpy as np

from analytics import residual
from analytics.common import load_thresholds
from tests.mock_data import make_mock

TH = load_thresholds()
OLD_KEYS = ("mean", "sigma", "sigma_mult", "trip", "n")


def _ref():
    normal, _ = make_mock("N")
    return residual.calibrate(normal, TH)


def _drift(trend, ref=None):
    return [a for a in residual.detect(trend, TH, ref or _ref()) if a.type == "residual_drift"]


def test_n_and_s1_have_no_residual_drift():
    for sc in ("N", "S1"):
        trend, _ = make_mock(sc)
        assert _drift(trend) == [], sc


def test_old_trip_would_have_fired_on_s1():
    """Documents the bug being fixed: the absolute-residual (old-style) reference false-alarms on S1."""
    ref = _ref()
    old = {k: ref[k] for k in OLD_KEYS}
    trend, _ = make_mock("S1")
    assert len(residual.detect(trend, TH, old)) == 1


def test_s2_exactly_one_episode_below_oti_warning():
    trend, _ = make_mock("S2")
    a = _drift(trend)
    assert len(a) == 1
    assert a[0].timestamp.isoformat().startswith("2026-04-23")  # old absolute detector: 2026-04-23 12:00
    assert trend.loc[trend.timestamp <= a[0].timestamp, "OTI_C"].max() < TH["operating"]["top_oil_c"]["warning"]


def test_load_independence_mismatch_scaled_with_load():
    trend, _ = make_mock("N")
    ref = _ref()
    hi = trend.copy()
    last = hi.index >= 20 * 96
    rise = trend["twin_oil_C"] - trend["amb_C"]
    new_rise = rise.where(~last, rise * 2.0)  # high load: twin rise doubled
    hi["twin_oil_C"] = trend["amb_C"] + new_rise
    # plant mismatch is a fixed 3 % of the rise (unchanged noise), so it doubles in degrees at high load
    hi["residual_oil_C"] = trend["residual_oil_C"] + 0.03 * (new_rise - rise)
    assert (hi["residual_oil_C"][last] - trend["residual_oil_C"][last]).mean() > 0.5
    assert _drift(hi, ref) == []
    # the old absolute statistic cannot tell: same data against an old-style reference trips
    old = {k: ref[k] for k in OLD_KEYS}
    big = hi.copy()
    big["residual_oil_C"] = trend["residual_oil_C"] + 0.12 * (new_rise - rise)
    assert len(residual.detect(big, TH, old)) == 1


def test_meter_only_all_nan_returns_empty():
    trend, _ = make_mock("S2")
    trend["residual_oil_C"] = np.nan
    assert residual.detect(trend, TH, _ref()) == []
    assert residual.detect(trend, TH) == []


def test_old_style_reference_does_not_crash_and_still_detects():
    ref = _ref()
    old = {k: ref[k] for k in OLD_KEYS}
    trend, _ = make_mock("S2")
    assert len(residual.detect(trend, TH, old)) == 1


def test_missing_ambient_falls_back_to_absolute():
    trend, _ = make_mock("S2")
    ref = _ref()
    out = residual.detect(trend.drop(columns=["amb_C"]), TH, ref)
    assert len(out) == 1 and " C above the twin" in out[0].explanation
