"""Live plant with injectable anomalies: the twin and analytics must catch what is injected, and stay quiet otherwise."""
import warnings

import pytest

from sim.live import CATALOGUE, LiveSession

warnings.simplefilter("ignore")


def _run(s, n):
    out = None
    for _ in range(n):
        out = s.tick()
    return out


def _types(out):
    return {a.type for a in out["alerts"]}


@pytest.fixture(scope="module")
def base():
    s = LiveSession()
    _run(s, 150)
    return s


def test_normal_operation_raises_no_alerts():
    s = LiveSession()
    seen = set()
    for _ in range(300):
        seen |= _types(s.tick())
    assert not seen, seen


def test_same_seed_same_stream():
    a, b = LiveSession(seed=3), LiveSession(seed=3)
    assert _run(a, 20)["frame"]["OTI_C"] == _run(b, 20)["frame"]["OTI_C"]


# kind, params, ticks allowed, one of these alert types must appear
CASES = [
    ("overload", {"level_pu": 1.2}, 20, {"loading_high", "overcurrent", "hot_spot_high"}),
    ("phase_unbalance", {}, 20, {"current_unbalance"}),
    ("voltage_sag", {"factor": 0.88}, 20, {"voltage_low"}),
    ("voltage_high", {"factor": 1.12}, 20, {"voltage_high"}),
    ("through_fault", {"peak_pu": 8}, 8, {"through_fault"}),
    ("oil_theft", {}, 12, {"oil_theft", "oil_low"}),
    ("oil_leak", {"days": 1.5, "drop_pct": 20}, 60, {"oil_leak", "oil_low"}),
    ("sensor_jump", {"channel": "OTI_C", "offset": 15}, 10, {"jump_sensor"}),
    ("sensor_stuck", {"channel": "OTI_C"}, 40, {"stuck_sensor"}),
]


@pytest.mark.parametrize("kind,params,n,expect", CASES, ids=[c[0] for c in CASES])
def test_injected_anomaly_is_detected(kind, params, n, expect):
    s = LiveSession()
    _run(s, 150)
    before = _types(s.tick())
    s.inject(kind, **params)
    seen = set()
    for _ in range(n):
        seen |= _types(s.tick())
    assert expect & (seen - before), f"{kind}: expected one of {expect}, got {seen}"


def test_cooling_fault_is_caught_by_the_residual_before_plain_thresholds():
    s = LiveSession()
    _run(s, 100)
    s.inject("cooling_fault", severity=1.4)
    first = {}
    for k in range(1, 260):
        for a in s.tick()["alerts"]:
            first.setdefault(a.type, k)
    assert "residual_drift" in first
    plain = [first[t] for t in ("top_oil_high", "hot_spot_high") if t in first]
    assert not plain or first["residual_drift"] < min(plain)


def test_clear_removes_injections_and_refill_restores_oil():
    s = LiveSession()
    _run(s, 10)
    s.inject("oil_leak", days=1.0, drop_pct=20)
    s.inject("overload")
    assert {i["kind"] for i in s.active()} == {"oil_leak", "overload"}
    assert s.clear(kind="overload") == 1
    _run(s, 40)
    low = s.last["frame"]["OLI_pct"]
    s.refill_oil()
    _run(s, 5)
    assert s.last["frame"]["OLI_pct"] > low + 5
    assert s.active() == []


def test_bad_injection_is_rejected():
    s = LiveSession()
    with pytest.raises(ValueError):
        s.inject("nonsense")
    with pytest.raises(ValueError):
        s.inject("overload", level_pu=9)
    with pytest.raises(ValueError):
        s.inject("sensor_stuck", channel="IR")


def test_frame_has_what_the_3d_view_reads():
    f = _run(LiveSession(), 5)["frame"]
    for col in ("OTI_C", "twin_oil_C", "twin_hs_C", "hs_ageing_C", "residual_oil_C", "OLI_pct", "IR", "IY", "IB", "amb_C",
                "load_pu", "bottom_oil_C", "oil_flow_intensity", "losses_total_W", "aging_rate", "health_score"):
        assert col in f, col


def test_every_catalogue_entry_can_be_injected():
    for kind, spec in CATALOGUE.items():
        s = LiveSession()
        p = {"channel": "OTI_C"} if spec.get("channel") else {}
        assert s.inject(kind, **p)["kind"] == kind
        s.tick()
