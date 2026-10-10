import numpy as np
import pytest

from tests.mock_data import SCENARIOS, TREND_COLS, ground_truth, make_mock


def test_all_scenarios_build_with_expected_columns():
    for s in SCENARIOS:
        trend, events = make_mock(s)
        assert list(trend.columns) == TREND_COLS
        assert len(trend) == 30 * 96
        assert trend["simulated"].all() and (trend["source"] == "mock").all()


def test_deterministic_for_a_seed():
    a, _ = make_mock("S2", seed=3)
    b, _ = make_mock("S2", seed=3)
    assert a.equals(b)


def test_normal_is_physical_and_residual_small():
    t, ev = make_mock("N")
    assert ev.empty
    assert 40 < t["OTI_C"].max() < 85  # plausible oil temperatures at ~0.6 pu in Bengaluru
    assert abs(t["residual_oil_C"].mean()) < 3
    assert t["gt_fault"].eq("").all()


def test_each_fault_leaves_its_signature():
    n, _ = make_mock("N")
    s1, _ = make_mock("S1")
    s2, _ = make_mock("S2")
    s3, _ = make_mock("S3")
    s4, _ = make_mock("S4")
    s5, ev = make_mock("S5")
    assert s1["loading_pct"].max() > 115
    assert s2["residual_oil_C"].iloc[-96 * 3 :].mean() > n["residual_oil_C"].iloc[-96 * 3 :].mean() + 5
    assert (s3[["IR", "IY", "IB"]].max(axis=1) / s3["I_mean"]).max() > 1.1
    assert s4["OLI_pct"].min() < 70
    assert len(ev) == 3 and ev["peak_pu"].max() == 10.0
    # short circuits are NOT visible in the 15-minute trend
    assert abs(s5["I_mean"].max() - n["I_mean"].max()) / n["I_mean"].max() < 0.05


def test_ground_truth_shape():
    assert ground_truth("N") == []
    for s in SCENARIOS[1:]:
        for g in ground_truth(s):
            assert {"fault", "onset", "end", "expect"} <= set(g)
    with pytest.raises(KeyError):
        ground_truth("nope")
