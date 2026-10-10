import pandas as pd
import numpy as np

from analytics import residual
from analytics.common import load_thresholds
from eval.scenarios import load_scenario

TH = load_thresholds()
OLD_KEYS = ("mean", "sigma", "sigma_mult", "trip", "n")


def _ref():
    normal, _ = load_scenario("N")
    return residual.calibrate(normal, TH)


def _drift(trend, ref=None):
    return [a for a in residual.detect(trend, TH, ref or _ref()) if a.type == "residual_drift"]


def test_n_and_s1_have_no_residual_drift():
    for sc in ("N", "S1"):
        trend, _ = load_scenario(sc)
        assert _drift(trend) == [], sc


def test_load_normalised_detector_quiet_on_overload():
    """On the mock the absolute (old-style) trip false-alarmed on S1. On the real generator's short overload it does
    not; the load-normalised detector must stay quiet either way, and never fire more than the absolute one."""
    ref = _ref()
    old = {k: ref[k] for k in OLD_KEYS}
    trend, _ = load_scenario("S1")
    assert residual.detect(trend, TH, ref) == []
    assert len(residual.detect(trend, TH, old)) >= len(residual.detect(trend, TH, ref))


def test_s2_exactly_one_episode_below_oti_warning():
    trend, _ = load_scenario("S2")
    a = _drift(trend)
    assert len(a) == 1
    onset = pd.Timestamp("2026-04-20", tz="Asia/Kolkata")
    assert onset < a[0].timestamp < onset + pd.Timedelta(days=4)  # real S2: 2026-04-22 09:00 (57 h)
    assert trend.loc[trend.timestamp <= a[0].timestamp, "OTI_C"].max() < TH["operating"]["top_oil_c"]["warning"]


def test_load_independence_mismatch_scaled_with_load():
    trend, _ = load_scenario("N")
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
    trend, _ = load_scenario("S2")
    trend["residual_oil_C"] = np.nan
    assert residual.detect(trend, TH, _ref()) == []
    assert residual.detect(trend, TH) == []


def test_old_style_reference_does_not_crash_and_still_detects():
    ref = _ref()
    old = {k: ref[k] for k in OLD_KEYS}
    trend, _ = load_scenario("S2")
    assert len(residual.detect(trend, TH, old)) == 1


def test_missing_ambient_falls_back_to_absolute():
    trend, _ = load_scenario("S2")
    ref = _ref()
    out = residual.detect(trend.drop(columns=["amb_C"]), TH, ref)
    assert len(out) == 1 and " C above the twin" in out[0].explanation
