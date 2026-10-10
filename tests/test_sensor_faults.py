import numpy as np
import pandas as pd
import pytest

from analytics import health, pipeline, sensor_faults
from analytics.common import load_thresholds, make_alert
from tests.mock_data import make_mock, mock_caps

TH = load_thresholds()
CAPS = mock_caps()


def inject(df: pd.DataFrame, kind: str, at: int = 1500) -> pd.DataFrame:
    """Return a copy of a mock trend with one injected sensor fault."""
    df = df.copy()
    if kind == "spike":  # 250 C single-sample OTI spike
        df.loc[at, "OTI_C"] = 250.0
    elif kind == "jump_in_range":  # +40 C single-sample OTI spike, still inside the 150 C range
        df.loc[at, "OTI_C"] = df.loc[at, "OTI_C"] + 40.0
    elif kind == "stuck":  # OTI frozen across the morning load ramp (30 samples)
        df.loc[at : at + 29, "OTI_C"] = df.loc[at, "OTI_C"]
    elif kind == "dead":  # WTI reads a 0/1 flag for the whole file
        df["WTI_C"] = (np.arange(len(df)) % 4 == 0).astype(float) * 0.0
    elif kind == "negcurrent":
        df.loc[at, "IR"] = -50.0
    else:
        raise ValueError(kind)
    return df


@pytest.fixture(scope="module")
def normal():
    return make_mock("N")


def types(alerts):
    return sorted({a.type for a in alerts})


def test_normal_mock_has_no_sensor_alerts():
    for seed in (0, 1, 2):
        df, _ = make_mock("N", seed=seed)
        assert sensor_faults.detect(df, TH, CAPS) == []


@pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5"])
def test_genuine_faults_are_not_sensor_faults(scenario):
    df, ev = make_mock(scenario)
    assert sensor_faults.detect(df, TH, CAPS) == []
    res = pipeline.analyze(df, ev, CAPS, TH)
    assert not [a for a in res.alerts if a.origin == "sensor"]


def test_s1_overload_stays_asset_origin():
    df, ev = make_mock("S1")
    res = pipeline.analyze(df, ev, CAPS, TH)
    assert any(a.type == "top_oil_high" or a.type == "loading_high" for a in res.alerts)
    assert all(a.origin == "asset" for a in res.alerts)


def test_spike_250c_detected_as_sensor(normal):
    df, _ = normal
    alerts = sensor_faults.detect(inject(df, "spike"), TH, CAPS)
    assert [(a.type, a.origin, a.module, a.detector) for a in alerts] == [("range_sensor", "sensor", "data", "physics")]
    assert alerts[0].value == 250.0 and alerts[0].timestamp == df.timestamp.iloc[1500]


def test_in_range_jump_detected(normal):
    df, _ = normal
    alerts = sensor_faults.detect(inject(df, "jump_in_range"), TH, CAPS)
    assert [a.type for a in alerts] == ["jump_sensor"]  # up and down edge are one episode
    assert alerts[0].origin == "sensor"


def test_jump_limit_scales_with_interval(normal):
    df, _ = normal
    d = df.iloc[::4].reset_index(drop=True)  # hourly: limit is 20 C per step
    bumped = d.copy()
    bumped.loc[300, "OTI_C"] += 12.0  # above 5 C/15 min if misread as 15-minute data, below 20 C/h
    assert sensor_faults.detect(bumped, TH, CAPS) == []
    bumped.loc[300, "OTI_C"] += 20.0
    assert [a.type for a in sensor_faults.detect(bumped, TH, CAPS)] == ["jump_sensor"]


def test_stuck_detected(normal):
    df, _ = normal
    alerts = sensor_faults.detect(inject(df, "stuck", at=7 * 96 + 28), TH, CAPS)  # morning ramp, day 7
    assert [(a.type, a.origin) for a in alerts] == [("stuck_sensor", "sensor")]
    assert "OTI_C" in alerts[0].id


def test_stuck_needs_load_change(normal):
    df, _ = normal
    d = df.copy()
    d.loc[100:130, "OTI_C"] = d.loc[100, "OTI_C"]
    d.loc[100:130, "load_pu"] = 0.5  # flat load: a flat temperature is then plausible
    assert [a for a in sensor_faults.detect(d, TH, CAPS) if a.type == "stuck_sensor"] == []


def test_dead_channel_detected(normal):
    df, _ = normal
    alerts = sensor_faults.detect(inject(df, "dead"), TH, CAPS)
    assert [(a.type, a.origin) for a in alerts] == [("dead_channel", "sensor")]
    assert "WTI_C" in alerts[0].id


def test_negative_current_detected(normal):
    df, _ = normal
    alerts = sensor_faults.detect(inject(df, "negcurrent"), TH, CAPS)
    assert [(a.type, a.origin) for a in alerts] == [("range_sensor", "sensor")]


def test_startup_zeros_are_not_a_sensor_fault(normal):
    df, _ = normal
    d = df.copy()
    zero = ["IR", "IY", "IB", "I_mean", "VR", "VY", "VB", "OTI_C", "WTI_C", "amb_C"]
    d.loc[10:20, zero] = 0.0  # device offline: every channel exactly 0
    assert sensor_faults.detect(d, TH, CAPS) == []
    d.loc[10:20, "VR"] = np.nan  # same idea with one channel missing
    assert sensor_faults.detect(d, TH, CAPS) == []


def test_single_phase_voltage_zero_is_flagged(normal):
    df, _ = normal
    d = df.copy()
    d.loc[50:52, "VR"] = 0.0
    a = sensor_faults.detect(d, TH, CAPS)
    assert [x.type for x in a] == ["range_sensor"] and "VR" in a[0].id


def test_dq_flags_become_alerts_without_duplicates(normal):
    df, _ = normal
    d = inject(df, "spike")
    d["dq_flags"] = ""
    d.loc[1500, "dq_flags"] = "RANGE_OTI"  # same sample the physics check already catches
    d.loc[800:802, "dq_flags"] = "STUCK_WTI;JUMP_OTI"  # not detectable from values
    alerts = sensor_faults.detect(d, TH, CAPS)
    assert sorted((a.type, a.id.split("-")[-1]) for a in alerts) == sorted(
        [("range_sensor", "OTI_C"), ("stuck_sensor", "WTI_C"), ("jump_sensor", "OTI_C")]
    )
    assert len({a.id for a in alerts}) == len(alerts)


def test_spike_asset_alert_is_relabelled_sensor(normal):
    df, ev = normal
    d = inject(df, "spike")
    res = pipeline.analyze(d, ev, CAPS, TH)
    top = [a for a in res.alerts if a.type == "top_oil_high"]
    assert top, "the 250 C spike must still trigger the rule alert (relabel, not delete)"
    assert all(a.origin == "sensor" for a in top)
    assert all("likely sensor/data fault, not an asset fault" in a.explanation for a in top)
    recs = {r.alert_id: r for r in res.recommendations}
    for a in top:
        assert a.recommendation_id and "device, not the transformer" in recs[a.id].action
    assert all(a.origin == "sensor" for a in res.alerts)  # nothing blamed on the asset


def test_sensor_critical_does_not_cap_health(normal):
    df, ev = normal
    base = health.compute(df, [], CAPS, TH)
    t = df.timestamp.iloc[-1]
    sensor_crit = make_alert(t, "range_sensor", "critical", "physics", origin="sensor")
    asset_crit = make_alert(t, "hot_spot_high", "critical", "rule")
    with_sensor = health.compute(df, [sensor_crit], CAPS, TH)
    assert with_sensor.score == base.score and not with_sensor.capped
    assert health.compute(df, [asset_crit], CAPS, TH).capped
    res = pipeline.analyze(inject(df, "spike", at=len(df) - 5), ev, CAPS, TH)
    assert any(a.severity == "critical" and a.origin == "sensor" for a in res.alerts)
    assert not res.health.capped


def test_short_and_missing_columns():
    df, _ = make_mock("N", days=1)
    assert sensor_faults.detect(df.iloc[:1], TH) == []
    assert sensor_faults.detect(df[["timestamp", "OTI_C"]], TH) == []
