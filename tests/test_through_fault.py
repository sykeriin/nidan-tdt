import pandas as pd

from analytics import through_fault as tf
from analytics.common import load_thresholds
from contracts.canonical import EVENT_COLUMNS as EVENT_COLS
from eval.scenarios import ground_truth, load_scenario

TH = load_thresholds()


def _events(peaks, ms=300, start="2026-04-01 10:00"):
    ts = pd.Timestamp(start, tz="Asia/Kolkata")
    rows = [
        {
            "timestamp": ts + pd.Timedelta(hours=i), "event_type": "through_fault", "phase": "3ph",
            "peak_pu": p, "duration_ms": ms, "i2t_pu2s": p**2 * ms / 1000.0, "source": "mock", "simulated": True,
        }
        for i, p in enumerate(peaks)
    ]
    return pd.DataFrame(rows, columns=EVENT_COLS)


def test_empty_events():
    empty = pd.DataFrame(columns=EVENT_COLS)
    assert tf.detect(empty, TH) == []
    assert tf.stress_table(empty, TH).empty
    assert list(tf.stress_table(empty, TH).columns) == tf.COLUMNS


def test_normal_scenario_has_no_events():
    _, ev = load_scenario("N")
    assert tf.detect(ev, TH) == []


def test_s5_alerts():
    _, ev = load_scenario("S5")
    alerts = tf.detect(ev, TH)
    kinds = [(a.type, a.severity) for a in alerts]
    assert kinds.count(("through_fault", "warning")) == 2
    assert kinds.count(("through_fault", "critical")) == 1
    stress = [a for a in alerts if a.type == "through_fault_stress"]
    assert len(stress) == 1 and stress[0].severity == "critical"
    assert "%X" in stress[0].explanation and "IS 1180" in stress[0].explanation
    onset = ground_truth("S5")[0]["onset"]
    assert min(a.timestamp for a in alerts) == onset
    assert stress[0].timestamp == ev.timestamp.iloc[1]  # crossed at the severe event
    assert all(a.simulated for a in alerts)


def test_stress_table_columns_and_cumulative():
    _, ev = load_scenario("S5")
    tbl = tf.stress_table(ev, TH)
    assert list(tbl.columns) == tf.COLUMNS
    assert list(tbl.severity_class) == ["moderate", "severe", "moderate"]
    assert tbl.cum_i2t_pu2s.iloc[-1] == ev.i2t_pu2s.sum()
    assert list(tbl.moderate_count_since_reset) == [1, 2, 3]
    assert list(tbl.triggered) == [False, True, True]


def test_three_moderate_events_trigger_without_severe():
    alerts = tf.detect(_events([3.2, 4.0, 5.0]), TH)
    stress = [a for a in alerts if a.type == "through_fault_stress"]
    assert len(stress) == 1 and stress[0].timestamp == _events([3.2, 4.0, 5.0]).timestamp.iloc[2]
    assert tf.detect(_events([3.2, 4.0]), TH)[-1].type == "through_fault"


def test_minor_events_do_not_alert_but_are_tabulated():
    ev = _events([1.5, 2.0])
    assert tf.detect(ev, TH) == []
    assert list(tf.stress_table(ev, TH).severity_class) == ["minor", "minor"]


def test_reset_at_ignores_earlier_events():
    ev = _events([9.0, 3.5, 3.5])
    reset = ev.timestamp.iloc[0]
    alerts = tf.detect(ev, TH, reset_at=reset)
    assert [a.type for a in alerts] == ["through_fault", "through_fault"]
    tbl = tf.stress_table(ev, TH, reset_at=reset)
    assert len(tbl) == 2 and list(tbl.moderate_count_since_reset) == [1, 2]
    assert tf.detect(ev, TH, reset_at=ev.timestamp.iloc[-1]) == []


def test_non_fault_events_are_ignored():
    ev = _events([10.0])
    ev["event_type"] = "tamper"
    assert tf.detect(ev, TH) == []
