"""Sensor-fault detection on the REAL Kaggle unit. Reads DT_KAGGLE_DIR at test time; skips when absent.

The data is third-party ("copyright-authors"): nothing from it is copied or embedded here. Only aggregate facts
observed on the data are asserted. Run with `pytest -s tests/test_sensor_faults_kaggle.py` to see the counts.
"""
import collections

import pytest

from analytics import pipeline, sensor_faults
from analytics.common import load_thresholds
from tests import kaggle_loader

pytestmark = pytest.mark.skipif(not kaggle_loader.available(), reason="Kaggle data directory not found (DT_KAGGLE_DIR)")

TH = load_thresholds()
LEAKY = {"OTI_A", "OTI_T", "MOG_A"}


@pytest.fixture(scope="module")
def real():
    df, info = kaggle_loader.load_kaggle()
    # The real unit has no twin columns and no load_pu: caps are empty so only channels that exist run.
    res = pipeline.analyze(df, df.iloc[:0], {}, TH)
    return df, info, res


def test_loader_contract(real):
    df, info, _ = real
    assert not LEAKY & set(df.columns)
    assert "loading_pct" not in df.columns and "load_pu" not in df.columns
    assert (df.source == "kaggle_real").all() and not df.simulated.any()
    assert df.timestamp.dt.tz is not None and df.timestamp.is_unique and df.timestamp.is_monotonic_increasing
    assert (df.timestamp.dt.minute % 15 == 0).all()
    assert info["overview_duplicate_timestamps_removed"] >= 0
    print("\nKaggle loader info:", info)


def test_250c_maximum_flagged_as_sensor_fault(real):
    df, _, res = real
    assert df.OTI_C.max() == 250.0
    t = df.loc[df.OTI_C.idxmax(), "timestamp"]
    eps = [e for e in sensor_faults.episodes(df) if e.channel == "OTI_C" and e.start_ts <= t <= e.end_ts]
    assert any(e.type == "range_sensor" for e in eps)
    assert all(a.origin == "sensor" for a in res.alerts if a.type == "range_sensor")


def test_dead_wti_flagged(real):
    df, _, res = real
    assert df.WTI_C.max() <= 1.0
    dead = [a for a in res.alerts if a.type == "dead_channel"]
    assert [a.id.split("-")[-1] for a in dead] == ["WTI_C"] and dead[0].origin == "sensor"


def test_no_raw_glitch_reported_as_asset_alert(real):
    df, _, res = real
    top = [a for a in res.alerts if a.type == "top_oil_high"]
    assert top
    lo, hi = sensor_faults.TEMP_RANGE_C
    by_ts = df.set_index("timestamp").OTI_C
    for a in top:
        if a.origin == "asset":
            assert lo <= by_ts[a.timestamp] <= hi  # an asset alert never rests on an out-of-range reading
        else:
            assert "likely sensor/data fault" in a.explanation
    # every glitch sample above the range limit sits inside a sensor-origin alert or a relabelled one
    assert not [a for a in top if a.origin == "asset" and a.value > hi]
    assert not [a for a in res.alerts if a.type == "hot_spot_high"]  # WTI is dead: it cannot raise a hot-spot alarm
    sensor_recs = {r.alert_id: r for r in res.recommendations}
    assert all("device, not the transformer" in sensor_recs[a.id].action for a in res.alerts if a.origin == "sensor")


def test_sensor_alerts_do_not_hit_health(real):
    _, _, res = real
    assert not res.health.capped


def test_report_counts(real):
    _, _, res = real
    sensor = collections.Counter(a.type for a in res.alerts if a.origin == "sensor")
    asset = collections.Counter(a.type for a in res.alerts if a.origin == "asset")
    print("\nKaggle sensor-origin alerts by type:", dict(sorted(sensor.items())))
    print("Kaggle asset-origin alerts by type:", dict(sorted(asset.items())))
    assert sensor and set(sensor) <= {"jump_sensor", "range_sensor", "stuck_sensor", "dead_channel", "top_oil_high"}
