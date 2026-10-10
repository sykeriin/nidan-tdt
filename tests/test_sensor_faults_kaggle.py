"""Real Kaggle unit through adapter -> twin -> analytics: a bad sensor gives sensor alerts only.

Requirements (integration of P3 with the twin's plausibility check, PRD 7.4 / 8.6):
- the residual detector is off because OTI fails the physics plausibility check;
- the 245-250 C plateaus and the oil-level drift give sensor-origin alerts only;
- no asset alert rests on the bad OTI (or on the drifting oil gauge).
Run with `pytest -s` to print the counts.
"""
import collections

import pytest

from analytics import pipeline, sensor_faults
from analytics.common import load_thresholds
from eval.scenarios import kaggle

LEAKY = {"alarm_oti_a", "alarm_oti_t", "alarm_mog_a", "alarm_wti", "alarm_OTI_A", "alarm_MOG_A"}


@pytest.fixture(scope="module")
def real():
    df, caps = kaggle()
    th = load_thresholds(asset={"i_rated_A": 214.7, "lv_voltage_V": 417.5, "nameplate_source": "estimated"})
    res = pipeline.analyze(df, df.iloc[:0], caps, th)
    return df, caps, res


def test_residual_off_because_oti_fails_plausibility(real):
    df, caps, res = real
    assert df.attrs["plausibility"]["OTI_C"] == "suspect"
    assert caps["residual_fidelity"] is False
    assert not [a for a in res.alerts if a.type == "residual_drift"]


def test_plateaus_are_sensor_faults(real):
    df, _, res = real
    hot = df[df["OTI_C"] > 150]
    assert len(hot)
    eps = sensor_faults.episodes(df)
    for t in hot["timestamp"]:
        assert any(e.channel == "OTI_C" and e.type in ("range_sensor", "jump_sensor") and e.start_ts <= t <= e.end_ts
                   for e in eps)
    assert all(a.origin == "sensor" for a in res.alerts if a.type in ("range_sensor", "jump_sensor"))


def test_oil_drift_is_a_sensor_fault(real):
    _, _, res = real
    drift = [a for a in res.alerts if a.type == "drift_sensor"]
    assert drift and all(a.origin == "sensor" for a in drift)
    first = min(a.timestamp for a in drift)
    assert first.year == 2019 and 9 <= first.month <= 10          # the Sep-Nov 2019 rise 40 -> 100 %


def test_no_asset_alerts_from_bad_oti_or_oil_gauge(real):
    _, _, res = real
    asset = [a for a in res.alerts if a.origin == "asset"]
    assert not [a for a in asset if a.type == "residual_drift"]
    # a top-oil alarm may only come from the twin's estimate (load-driven), never from the measured OTI
    assert all("twin-estimated" in a.explanation for a in asset if a.type == "top_oil_high")
    assert not [a for a in asset if a.module == "oil"]
    implaus = [a for a in res.alerts if a.type == "implausible_sensor"]
    assert implaus and all(a.origin == "sensor" for a in implaus)
    assert "can't be reading top-oil" in implaus[0].explanation


def test_ingestion_already_removed_bad_channels(real):
    df, _, _ = real
    assert "WTI_C" not in df.columns                               # 0/1 flag, mapped to alarm_WTI at ingestion
    assert not LEAKY & set(c for c in pipeline._clean(df).columns)  # device alarms never reach detectors


def test_sensor_alerts_get_device_advice(real):
    _, _, res = real
    recs = {r.alert_id: r for r in res.recommendations}
    assert all("device, not the transformer" in recs[a.id].action for a in res.alerts if a.origin == "sensor")


def test_report_counts(real):
    _, _, res = real
    sensor = collections.Counter(a.type for a in res.alerts if a.origin == "sensor")
    asset = collections.Counter(a.type for a in res.alerts if a.origin == "asset")
    print("\nKaggle sensor-origin alerts by type:", dict(sorted(sensor.items())))
    print("Kaggle asset-origin alerts by type:", dict(sorted(asset.items())))
    assert sensor
    assert set(asset) <= {"loading_high", "overcurrent", "current_unbalance", "voltage_unbalance", "voltage_high",
                          "voltage_low", "hot_spot_high", "ageing_rate_high", "top_oil_high"}


def test_real_data_is_not_flooded(real):
    """Tuned on the real unit: one alert per condition, not one per noisy sample."""
    _, _, res = real
    n = collections.Counter(a.type for a in res.alerts)
    assert n["current_unbalance"] <= 10          # chronic unbalance (median 25 %): was 2,042 alerts
    assert n["stuck_sensor"] <= 30               # saturated oil gauge, merged per data segment: was 390
    assert n["jump_sensor"] <= 30                # real >= 5 C steps only (1-min ticks of a 1 C sensor are not jumps)
    assert all(abs(a.value) >= 5 for a in res.alerts if a.type == "jump_sensor")
    assert len(res.alerts) < 200


def test_rating_dependent_alerts_are_indicative_with_estimated_rating(real):
    _, _, res = real
    rated = [a for a in res.alerts if a.type in pipeline.RATING_DEPENDENT and a.origin == "asset"]
    assert rated and all(a.severity == "info" and "indicative only" in a.explanation for a in rated)
    assert not res.health.capped or any(a.severity == "critical" and a.type not in pipeline.RATING_DEPENDENT
                                        for a in res.alerts)
