import pandas as pd

from analytics import recommend
from analytics.common import ALERT_MODULES, load_thresholds, make_alert
from contracts.models import Health

TH = load_thresholds()
T0 = pd.Timestamp("2026-04-10 08:00", tz="Asia/Kolkata")
GREEN = Health(score=95.0, band="Green", components={}, weights={}, capped=False)
RED = Health(score=35.0, band="Red", components={}, weights={}, capped=True)
URGENCIES = {"immediate", "24h", "7d", "next_scheduled"}


def _alert(t, ts=T0, sev="warning", **kw):
    kw.setdefault("value", 1.5)
    return make_alert(ts, t, sev, "rule", threshold=1.0, **kw)


def test_every_alert_type_gets_a_recommendation_and_id():
    alerts = [_alert(t, ts=T0 + pd.Timedelta(minutes=15 * i)) for i, t in enumerate(ALERT_MODULES)]
    recs = recommend.build(alerts, GREEN, TH)
    ids = {r.id for r in recs}
    assert len(ids) == len(recs)
    for a in alerts:
        mine = [r for r in recs if r.alert_id == a.id]
        assert mine, a.type
        assert a.recommendation_id in ids
        for r in mine:
            assert r.action and r.rationale and r.urgency in URGENCIES
            assert r.id.endswith("-oil") or "= 1.5" in r.rationale


def test_rationale_names_signal_and_value():
    r = recommend.build([_alert("oil_low", value=None)], GREEN, TH)[0]
    assert "OLI_pct" in r.rationale
    a = make_alert(T0, "hot_spot_high", "critical", "rule", value=131.0, threshold=120.0)
    r = recommend.build([a], GREEN, TH)[0]
    assert "hot-spot" in r.rationale and "131" in r.rationale and r.urgency == "24h"


def test_urgency_by_severity_and_fixed_rows():
    alerts = [_alert("oil_theft", sev="critical"), _alert("current_unbalance"),
              _alert("through_fault_stress", sev="critical"), _alert("loading_high")]
    by = {a.type: recommend.build([a], GREEN, TH)[0] for a in alerts}
    assert by["oil_theft"].urgency == "immediate"
    assert by["current_unbalance"].urgency == "7d"
    assert by["through_fault_stress"].urgency == "7d"
    assert by["loading_high"].urgency == "7d"
    assert "IS 1180" in by["through_fault_stress"].action
    assert "verify" in by["through_fault_stress"].standard_ref


def test_voltage_alerts_get_cautious_supply_recommendation():
    for t in ("voltage_high", "voltage_low", "voltage_unbalance"):
        r = recommend.build([_alert(t)], GREEN, TH)[0]
        assert "utility" in r.action and r.standard_ref is None


def test_sensor_alert_points_to_device():
    a = _alert("top_oil_high", origin="sensor")
    r = recommend.build([a], GREEN, TH)[0]
    assert "not the transformer" in r.action and r.urgency == "24h"


def test_compound_residual_plus_oil_within_24h():
    res = _alert("residual_drift", ts=T0)
    leak = _alert("oil_leak", ts=T0 + pd.Timedelta(hours=10))
    recs = recommend.build([res, leak], GREEN, TH)
    comp = [r for r in recs if r.action.startswith("Oil leakage check; insulation resistance test") and r.alert_id == res.id]
    assert len(comp) == 1 and comp[0].urgency == "24h"
    assert res.recommendation_id == comp[0].id
    assert any("cooling" in r.action.lower() for r in recs if r.alert_id == res.id)


def test_no_compound_when_oil_alert_far_away():
    res = _alert("residual_drift", ts=T0)
    low = _alert("oil_low", ts=T0 + pd.Timedelta(hours=30))
    recs = recommend.build([res, low], GREEN, TH)
    assert len([r for r in recs if r.alert_id == res.id]) == 1


def test_red_band_adds_tan_delta_linked_to_latest_critical():
    a1 = _alert("hot_spot_high", ts=T0, sev="critical")
    a2 = _alert("oil_theft", ts=T0 + pd.Timedelta(hours=2), sev="critical")
    recs = recommend.build([a1, a2], RED, TH)
    td = recs[-1]
    assert td.urgency == "7d" and "Tan-delta" in td.action and td.alert_id == a2.id
    assert "verify" in td.standard_ref


def test_red_band_without_alerts_links_health():
    recs = recommend.build([], RED, TH)
    assert len(recs) == 1 and recs[0].alert_id == "health"
    assert recommend.build([], GREEN, TH) == []
