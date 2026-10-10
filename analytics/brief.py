"""The plain-language picture at one moment: status sentence, ranked diagnosis, maintenance work order, headroom.

    brief(run, t) -> dict

Everything is read from the run (measured trend, twin columns, alerts, recommendations, Health Index); nothing is
hard-coded for show. Diagnosis classes that need a channel the dataset lacks say so ("not observable") instead of
guessing. The evidence scores are smooth ramps over measured quantities and active alerts: engineering judgement,
labelled as such, not a trained classifier.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from contracts.models import Run
from twin import forecast

ACTIVE_H = 24                     # alerts raised in the last 24 h are "active" (same window as the replay state)
LONG_H = 24 * 7                   # events and oil losses stay relevant for a week
URGENCY_RANK = {"immediate": 0, "24h": 1, "7d": 2, "next_scheduled": 3}
URGENCY_TEXT = {"immediate": "Immediately", "24h": "Within 24 hours", "7d": "Within 7 days", "next_scheduled": "At the next scheduled inspection"}
PRIORITY = {"immediate": "Immediate", "24h": "Urgent", "7d": "Soon", "next_scheduled": "Routine"}

LABELS = {
    "cooling": "Cooling degradation", "overload": "Overload", "voltage": "Voltage excursion", "unbalance": "Phase unbalance",
    "short_circuit": "Through-fault stress", "oil": "Oil loss", "sensor": "Sensor or data fault",
}


def ramp(x: float | None, a: float, b: float) -> float:
    if x is None or not np.isfinite(x):
        return 0.0
    return float(np.clip((x - a) / (b - a), 0.0, 1.0))


def _row_at(trend: pd.DataFrame, t: pd.Timestamp) -> pd.Series | None:
    if "timestamp" not in trend or trend.empty:
        return None
    i = trend["timestamp"].searchsorted(t, side="right") - 1
    return trend.iloc[i] if i >= 0 else None


def _num(row: pd.Series | None, col: str) -> float | None:
    if row is None or col not in row.index:
        return None
    v = row[col]
    return None if v is None or pd.isna(v) else float(v)


def _health_at(run: Run, t: pd.Timestamp) -> tuple[float | None, str | None]:
    hs = run.health_series
    if hs is None or hs.empty or "timestamp" not in hs:
        h = run.analysis.health
        return h.score, str(h.band).lower()
    i = hs["timestamp"].searchsorted(t, side="right") - 1
    if i < 0:
        return None, None
    score = float(hs["score"].iloc[i])
    return score, ("green" if score >= 80 else "yellow" if score >= 60 else "red")


def _alerts(run: Run, t: pd.Timestamp, hours: float, types=None, origin: str | None = None):
    lo = t - pd.Timedelta(hours=hours)
    return [a for a in run.analysis.alerts
            if lo < pd.Timestamp(a.timestamp) <= t and (types is None or a.type in types) and (origin is None or a.origin == origin)]


def _sev(alerts) -> float:
    return max((1.0 if a.severity == "critical" else 0.7 if a.severity == "warning" else 0.4 for a in alerts), default=0.0)


def _diagnosis(run: Run, t: pd.Timestamp, row: pd.Series | None, K: float | None, rel: float | None, unb: float | None,
               vdev: float | None) -> list[dict]:
    caps = run.capabilities
    asset_act = _alerts(run, t, ACTIVE_H, origin="asset")
    evidence: dict[str, tuple[float, str, bool]] = {}

    cool = _alerts(run, t, ACTIVE_H, {"residual_drift"})
    e = max(0.9 if cool else 0.0, ramp(rel, 0.03, 0.12))
    observable = bool(caps.get("residual_fidelity"))
    evidence["cooling"] = (e if observable else 0.0,
                           f"The top oil is {rel * 100:.0f} % hotter above ambient than the physics predicts for this load." if rel is not None and rel > 0.02
                           else "Top oil follows the physics prediction.", observable)

    over = _alerts(run, t, ACTIVE_H, {"loading_high", "overcurrent", "hot_spot_high", "ageing_rate_high", "top_oil_high"}, "asset")
    hs = _num(row, "twin_hs_C")
    w = run.trend[(run.trend["timestamp"] <= t) & (run.trend["timestamp"] > t - pd.Timedelta(hours=ACTIVE_H))]
    k_pk = float(w["load_pu"].max()) if "load_pu" in w and w["load_pu"].notna().any() else K
    hs_pk = float(w["twin_hs_C"].max()) if "twin_hs_C" in w and w["twin_hs_C"].notna().any() else hs
    e = max(ramp(k_pk, 0.9, 1.25), 0.8 * _sev(over), 0.6 * ramp(hs_pk, 98, 120))
    if cool and e > 0:
        e *= 0.5 if (k_pk or 0) < 1.0 else 1.0           # a hot oil at normal load is cooling, not load
    evidence["overload"] = (e, f"Load peaked at {k_pk:.2f} pu in the last 24 h and the hot spot reached {hs_pk:.0f} °C." if k_pk is not None and hs_pk is not None else "No load reading.", True)

    volt = _alerts(run, t, ACTIVE_H, {"voltage_high", "voltage_low", "voltage_unbalance"}, "asset")
    ok = bool(caps.get("voltage_quality"))
    evidence["voltage"] = (max(ramp(abs(vdev) if vdev is not None else None, 0.04, 0.10), 0.8 * _sev(volt)) if ok else 0.0,
                           f"Phase voltage is {vdev * 100:+.1f} % from nominal." if vdev is not None else "No voltage readings.", ok)

    unb_a = _alerts(run, t, ACTIVE_H, {"current_unbalance"}, "asset")
    ok = bool(caps.get("unbalance"))
    evidence["unbalance"] = (max(ramp(unb, 8, 22), 0.8 * _sev(unb_a)) if ok else 0.0,
                             f"Phase currents differ by {unb:.0f} % from their mean." if unb is not None else "No per-phase currents.", ok)

    sc = _alerts(run, t, LONG_H, {"through_fault", "through_fault_stress"}, "asset")
    ok = bool(caps.get("through_fault"))
    evidence["short_circuit"] = (min(1.0, 0.45 * len([a for a in sc if a.type == "through_fault"]) + (0.6 if any(a.type == "through_fault_stress" for a in sc) else 0.0)) if ok else 0.0,
                                 f"{len([a for a in sc if a.type == 'through_fault'])} through-fault event(s) in the last week." if sc else "No through-faults recorded.", ok)

    oil = _alerts(run, t, LONG_H, {"oil_leak", "oil_low", "oil_theft"}, "asset")
    ok = bool(caps.get("oil_leak_theft"))
    lvl = _num(row, "OLI_pct")
    gauge_bad = any(a.type == "drift_sensor" or "oil level" in a.explanation.lower() for a in _alerts(run, t, LONG_H, None, "sensor"))
    e_oil = max(0.9 * _sev(oil), ramp(None if lvl is None else 97 - lvl, 3, 12)) * (0.25 if gauge_bad else 1.0)
    evidence["oil"] = (e_oil if ok else 0.0,
                       (f"Oil level reads {lvl:.0f} %, but the gauge is flagged as faulty, so this is not taken as oil loss." if gauge_bad
                        else f"Oil level is {lvl:.0f} %.") if lvl is not None else "No oil-level reading.", ok)

    sens = _alerts(run, t, ACTIVE_H, None, "sensor")
    evidence["sensor"] = (min(1.0, 0.25 * len(sens)), f"{len(sens)} sensor-origin alert(s): check the device, not the transformer." if sens else "No sensor faults.", True)

    total = sum(v[0] for v in evidence.values())
    out = []
    for key, (e, why, observable) in evidence.items():
        out.append({"fault": key, "label": LABELS[key], "evidence": round(e, 3), "share": round(e / total, 3) if total > 0 and e >= 0.15 else 0.0,
                    "observable": observable, "why": why if observable else "Not observable with these inputs."})
    out.sort(key=lambda d: (not d["observable"], -d["evidence"]))
    return out


DEFAULT_ACTION = {   # FINAL_PRD section 8.10, used when a condition is present but no alert carries a recommendation yet
    "cooling": ("Inspect radiators and cooling; check oil level", "Radiator and cooling inspection; oil level check"),
    "overload": ("Review load and transfer load if possible; check cooling", "Load review; cooling check"),
    "voltage": ("Check the tap position and the supply voltage", "Voltage survey at the LV bus"),
    "unbalance": ("Rebalance single-phase loads; check connections and neutral", "Load balance survey; connection check"),
    "short_circuit": ("Measure short-circuit impedance (%X) and compare with the IS 1180 limit", "Short-circuit impedance measurement"),
    "oil": ("Check the oil level and inspect the tank and gaskets", "Oil level check; leak inspection"),
    "sensor": ("Check sensor wiring and calibration; the fault is in the device, not the transformer", "Sensor check"),
}


def _advice(run: Run, t: pd.Timestamp, band: str | None, active_asset, diag_top: dict | None = None) -> dict:
    recs = {r.alert_id: r for r in run.analysis.recommendations}
    chosen = {}
    for a in _alerts(run, t, LONG_H, None, "asset") + _alerts(run, t, ACTIVE_H, None, "sensor"):
        r = recs.get(a.id)
        if r and (a in active_asset or a.type in {"oil_leak", "oil_low", "oil_theft", "through_fault_stress"} or a.origin == "sensor"):
            key = (r.action, r.test)
            if key not in chosen or URGENCY_RANK[r.urgency] < URGENCY_RANK[chosen[key][0].urgency]:
                chosen[key] = (r, a)
    ranked = sorted(chosen.values(), key=lambda ra: (URGENCY_RANK[ra[0].urgency], ra[1].timestamp))
    fallback = []
    if not ranked and diag_top is not None:
        act, test = DEFAULT_ACTION[diag_top["fault"]]
        fallback = [{"action": act, "test": test, "urgency": "7d", "why": diag_top["why"], "standard_ref": None, "alert_id": None,
                     "alert_type": diag_top["fault"]}]
    crit = any(a.severity == "critical" for a in active_asset)
    if ranked:
        top = ranked[0][0].urgency
    elif band == "red" or crit or fallback:
        top = "7d"
    elif band == "yellow":
        top = "7d"
    else:
        top = "next_scheduled"
    priority = PRIORITY[top]
    schedule = ("Within 30 days (Health Index is in the yellow band)." if not ranked and band == "yellow"
                else URGENCY_TEXT[top] + ("" if top != "next_scheduled" else " (routine)"))
    return {"priority": priority, "schedule": schedule, "urgency": top,
            "actions": [{"action": r.action, "test": r.test, "urgency": r.urgency, "why": r.rationale.split(";")[-1].strip() if r.rationale else "",
                         "standard_ref": r.standard_ref, "alert_id": a.id, "alert_type": a.type}
                        for r, a in ranked[:6]] or fallback,
            "note": "Schedules follow the Health Index band and the urgency of the recommendations; they are engineering guidance, not a work order issued by a utility."}


def brief(run: Run, t) -> dict:
    t = pd.Timestamp(t)
    tz = run.trend["timestamp"].dt.tz if "timestamp" in run.trend else None
    if tz is not None:
        t = t.tz_localize(tz) if t.tzinfo is None else t.tz_convert(tz)       # hour-of-day logic must use the data's own zone
    tr = run.trend
    asset = {k: v for k, v in run.asset.items() if k != "profile_notes"}
    if run.mode in ("snapshot", "data_only") or "timestamp" not in tr:
        return {"level": "nodata", "sentence": "This dataset has no time axis, so there is no timeline to describe. Use the ranked records instead.",
                "diagnosis": [], "advice": None, "kpis": {}}
    row = _row_at(tr, t)
    if row is None:
        return {"level": "nodata", "sentence": "No data yet at this time.", "diagnosis": [], "advice": None, "kpis": {}}
    i_rated = float(asset.get("i_rated_A") or np.nan)
    K = _num(row, "load_pu")
    if K is None and np.isfinite(i_rated) and _num(row, "I_mean") is not None:
        K = _num(row, "I_mean") / i_rated
    oti, twin_oil, hs_t, amb = _num(row, "OTI_C"), _num(row, "twin_oil_C"), _num(row, "twin_hs_C"), _num(row, "amb_C")
    rel = None
    if oti is not None and twin_oil is not None and amb is not None and twin_oil - amb > 8 and run.mode == "full":
        rel = (oti - twin_oil) / (twin_oil - amb)
    ph = [_num(row, c) for c in ("IR", "IY", "IB")]
    unb = None
    if all(p is not None for p in ph) and np.mean(ph) > 0.05 * i_rated:
        unb = max(abs(p - np.mean(ph)) for p in ph) / np.mean(ph) * 100
    vph = [_num(row, c) for c in ("VR", "VY", "VB")]
    vdev = None
    if all(v is not None for v in vph) and asset.get("lv_voltage_V"):
        vdev = float(np.mean(vph)) / (float(asset["lv_voltage_V"]) / np.sqrt(3)) - 1.0
    score, band = _health_at(run, t)
    active = _alerts(run, t, ACTIVE_H, None, "asset")
    diag = _diagnosis(run, t, row, K, rel, unb, vdev)
    top = next((d for d in diag if d["observable"] and d["evidence"] >= 0.4), None)
    adv = _advice(run, t, band, active, top)

    crit = any(a.severity == "critical" for a in active) or band == "red"
    warn = any(a.severity == "warning" for a in active) or band == "yellow" or top is not None
    level = "critical" if crit else "watch" if warn else "good"

    kpis: dict = {}
    if np.isfinite(i_rated) and K is not None and amb is not None:
        kpis["headroom"] = forecast.headroom(asset, amb)
        if twin_oil is not None:
            kpis["time_to_limit"] = forecast.time_to_limit(asset, K, amb, twin_oil)
    kpis["ageing_rate"] = _num(row, "aging_rate_actual") if _num(row, "aging_rate_actual") is not None else _num(row, "aging_rate")
    kpis["residual_pct"] = None if rel is None else round(rel * 100, 1)
    kpis["unbalance_pct"] = None if unb is None else round(unb, 1)

    name = str(asset.get("name") or "The transformer")
    reading = f"hot spot {hs_t:.0f} °C" if hs_t is not None else "no temperature estimate"
    when = adv["schedule"].rstrip(".")
    if level == "good":
        rate = kpis["ageing_rate"]
        sentence = (f"{name} is in good condition. Load is {K * 100:.0f} % of rating, {reading}"
                    f"{'' if rate is None else f', ageing at {rate:.2f} times the design rate'}. Next step: {when[0].lower() + when[1:]}.")
    else:
        lead = f"{top['label']}: {top['why']}" if top else "A threshold was crossed."
        act = adv["actions"][0]["action"] if adv["actions"] else None
        sentence = f"{lead}{'' if act is None else f' Recommended: {act[0].lower() + act[1:]}.'} {adv['schedule'].rstrip('.')}."
        if level == "watch":
            sentence = sentence.replace("Recommended", "Suggested", 1)
    return {"t": t.isoformat(), "level": level, "sentence": sentence, "health": {"score": None if score is None else round(score, 1), "band": band},
            "diagnosis": diag, "advice": adv, "kpis": kpis}
