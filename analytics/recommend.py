"""Recommendation engine (FINAL_PRD section 8.10). OWNER: Agent B (scoring and advice).

Contract:
    build(alerts, health, thresholds) -> list[Recommendation]
Table: FINAL_PRD section 8.10. Every alert type in analytics.common.ALERT_MODULES maps to at least
one recommendation. Each recommendation: action, test, urgency (immediate|24h|7d|next_scheduled),
rationale (names the triggering signal and value), alert_id, standard_ref. It also sets
alert.recommendation_id (the primary recommendation for that alert; a compound one wins when it applies).

Rules beyond the one-row-per-type table:
    sensor-origin alerts -> "check the device, not the transformer" (24h), replacing the asset advice.
    residual_drift with an oil_low/oil_leak alert within COMPOUND_WINDOW_H -> oil leakage check; insulation
    resistance test (24h), in addition to the cooling inspection.
    Health band Red -> tan-delta / insulation assessment (7d), linked to the most recent critical alert
    (alert_id "health" if there is none).
standard_ref is None where the PRD names no standard. Test limits are never stated here.
"""
from __future__ import annotations

import pandas as pd

from contracts.models import Alert, Health, Recommendation

COMPOUND_WINDOW_H = 24.0
TAN_DELTA_REF = "Tan-delta recommended for distribution transformers by CEA [Reported]; to verify against the standard"
IS1180_REF = "IS 1180:2014 short-circuit acceptance limit (from CPRI presentation); to verify against the standard"
IEC_7_REF = "IEC 60076-7 loading guide; to verify against the standard"

# type -> (signal named in the rationale, action, test, urgency or (urgency if critical, otherwise), standard_ref)
_TABLE: dict[str, tuple[str, str, str | None, str | tuple[str, str], str | None]] = {
    "loading_high": ("load_pu", "Review load and transfer load if possible; check cooling; schedule an inspection",
                     "Cooling system and connection inspection", ("24h", "7d"), None),
    "overcurrent": ("load_pu / I_mean", "Review load and transfer load if possible; check cooling; schedule an inspection",
                    "Cooling system and connection inspection", ("24h", "7d"), None),
    "hot_spot_high": ("hot-spot temperature", "Review load and transfer load if possible; check cooling; schedule an inspection",
                      "Cooling system inspection", ("24h", "7d"), IEC_7_REF),
    "top_oil_high": ("top-oil temperature", "Review load and transfer load if possible; check cooling; schedule an inspection",
                     "Cooling system inspection", ("24h", "7d"), IEC_7_REF),
    "ageing_rate_high": ("ageing rate", "Review load and transfer load if possible; check cooling; schedule an inspection",
                         "Cooling system inspection", ("24h", "7d"), IEC_7_REF),
    "residual_drift": ("measured minus twin oil temperature (residual_oil_C)", "Inspect radiators and cooling; check oil level",
                       "Radiator and cooling inspection; oil level check", "7d", None),
    "current_unbalance": ("current unbalance %", "Rebalance single-phase loads; check connections and neutral",
                          "Connection and neutral inspection", "7d", None),
    "voltage_unbalance": ("voltage unbalance %", "Check supply voltage and tap setting with the utility",
                          "Supply voltage and tap position check", "7d", None),
    "voltage_high": ("phase voltage (pu)", "Check supply voltage and tap setting with the utility",
                     "Supply voltage and tap position check", "7d", None),
    "voltage_low": ("phase voltage (pu)", "Check supply voltage and tap setting with the utility",
                    "Supply voltage and tap position check", "7d", None),
    "oil_low": ("oil level (OLI_pct)", "Check oil level and inspect the tank and gaskets for leaks",
                "Oil leakage check", "24h", None),
    "oil_leak": ("oil level trend (OLI_pct)", "Inspect the tank and gaskets for leaks; check oil level",
                 "Oil leakage check; insulation resistance test", "24h", None),
    "oil_theft": ("oil level step (OLI_pct)", "Site inspection for oil theft or tampering",
                  "Site inspection", "immediate", None),
    "through_fault": ("through-fault event peak (pu)", "Log the through-fault event and review protection records",
                      "Short-circuit impedance (%X) measurement if the cumulative stress limit is crossed", "next_scheduled",
                      IS1180_REF),
    "through_fault_stress": ("cumulative through-fault stress", "Measure short-circuit impedance (%X) and compare with the IS 1180 limit",
                             "Short-circuit impedance (%X) measurement", "7d", IS1180_REF),
    "short_circuit_trip": ("short-circuit event peak (pu)", "Isolate and inspect: check protection records, then measure short-circuit impedance (%X) and compare with the IS 1180 limit",
                           "Short-circuit impedance (%X) and frequency-response (SFRA) test", "immediate", IS1180_REF),
    "turn_fault": ("winding minus twin hot-spot temperature", "De-energise when possible; shorted turns heat one winding locally and can progress to a full fault",
                   "Winding resistance, turns-ratio test and dissolved-gas analysis", "24h", None),
    "earth_leakage": ("tank earth current (IEARTH_A)", "Inspect for winding-to-tank insulation breakdown; check the earthing and the oil",
                      "Insulation resistance (megger) and tan-delta test", ("immediate", "7d"), TAN_DELTA_REF),
    "moisture_high": ("moisture in oil (H2O_ppm)", "Dry out the oil and check the breather and gaskets",
                      "Oil moisture (Karl Fischer) and breakdown voltage test", ("24h", "7d"), None),
    "silica_gel_exhausted": ("silica gel saturation (SILICA_pct)", "Replace or recharge the silica gel in the breather",
                             "Breather inspection", "7d", None),
    "charging_current": ("reactive power at low load (Q_kVAr)", "Check for an energised idle cable or line; switch it out or compensate",
                         None, "next_scheduled", None),
    "efficiency_low": ("efficiency (eta_pct)", "Look for extra loss: overheating, a shorted turn, loose joints or harmonics",
                       "Loss measurement and thermography", "7d", None),
    "temp_rise_fast": ("top-oil temperature rise rate", "Check load and cooling now; a fast rise is faster than weather or load usually explain",
                       "Cooling system inspection", "24h", IEC_7_REF),
    "frequency_off": ("supply frequency (freq_Hz)", "Check the supply and the grid operator's notices", None, "7d", None),
}


def _rationale(a: Alert, signal: str) -> str:
    text = f"{signal}"
    if a.value is not None:
        text += f" = {a.value:.4g}"
    if a.threshold is not None:
        text += f" (threshold {a.threshold:.4g})"
    text += f" at {a.timestamp:%Y-%m-%d %H:%M}"
    return f"{text}; {a.explanation}" if a.explanation else text


def _urgency(spec: str | tuple[str, str], severity: str) -> str:
    return spec if isinstance(spec, str) else (spec[0] if severity == "critical" else spec[1])


def _primary(a: Alert) -> Recommendation:
    rid = f"rec-{a.id}"
    if a.origin == "sensor":
        return Recommendation(
            id=rid, action="Check sensor wiring and calibration; the fault is in the device, not the transformer",
            test="Sensor wiring and calibration check", urgency="24h",
            rationale=_rationale(a, f"sensor-origin alert {a.type}"), alert_id=a.id, standard_ref=None,
        )
    if a.type not in _TABLE:
        return Recommendation(
            id=rid, action="Review the alert and inspect the transformer", test=None, urgency="next_scheduled",
            rationale=_rationale(a, a.type), alert_id=a.id, standard_ref=None,
        )
    signal, action, test, urgency, ref = _TABLE[a.type]
    return Recommendation(
        id=rid, action=action, test=test, urgency=_urgency(urgency, a.severity),
        rationale=_rationale(a, signal), alert_id=a.id, standard_ref=ref,
    )


def _compound(res: Alert, oil: Alert) -> Recommendation:
    gap_h = abs((res.timestamp - oil.timestamp) / pd.Timedelta(hours=1))
    return Recommendation(
        id=f"rec-{res.id}-oil", action="Oil leakage check; insulation resistance test",
        test="Insulation resistance test", urgency="24h",
        rationale=(
            f"residual_oil_C drift ({res.id}) together with {oil.type} ({oil.id}, OLI_pct) {gap_h:.1f} h apart "
            "suggests oil loss is raising the oil temperature"
        ),
        alert_id=res.id, standard_ref=None,
    )


def build(alerts: list[Alert], health: Health, thresholds: dict) -> list[Recommendation]:
    recs: list[Recommendation] = []
    oil_alerts = [a for a in alerts if a.type in ("oil_low", "oil_leak") and a.origin == "asset"]
    for a in alerts:
        primary = _primary(a)
        recs.append(primary)
        a.recommendation_id = primary.id
        if a.type == "residual_drift" and a.origin == "asset" and oil_alerts:
            near = [o for o in oil_alerts if abs(o.timestamp - a.timestamp) <= pd.Timedelta(hours=COMPOUND_WINDOW_H)]
            if near:
                nearest = min(near, key=lambda o: abs(o.timestamp - a.timestamp))
                compound = _compound(a, nearest)
                recs.append(compound)
                a.recommendation_id = compound.id
    if health.band == "Red":
        crit = [a for a in alerts if a.severity == "critical"]
        link = max(crit, key=lambda a: a.timestamp) if crit else None
        recs.append(
            Recommendation(
                id=f"rec-hi-{link.id if link else 'health'}",
                action="Tan-delta / insulation assessment; winding resistance measurement if a winding fault is suspected",
                test="Tan-delta and insulation assessment", urgency="7d",
                rationale=f"Health Index {health.score:.1f} is in the Red band" + (f"; latest critical alert {link.id}" if link else ""),
                alert_id=link.id if link else "health", standard_ref=TAN_DELTA_REF,
            )
        )
    return recs
