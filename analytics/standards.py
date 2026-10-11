"""India-profile condition detectors: moisture and silica gel, earth leakage (winding to tank), turn-to-turn insulation,
charging current on an idle line, efficiency, temperature rise rate, frequency band and short-circuit trip.

Contract:
    detect(df, events, thresholds) -> list[Alert]
Every detector reads only columns the plant or gateway reports; a missing column means no alert from that detector.
Limits come from thresholds.yaml `operating` (IS 2026 / IS 1180 / IS 1866 / CEA, see the notes there).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics.common import make_alert, runs, step_hours, strip_quarantined
from contracts.models import Alert


def _num(df: pd.DataFrame, col: str) -> pd.Series | None:
    if col not in df.columns:
        return None
    s = pd.to_numeric(df[col], errors="coerce")
    return None if s.isna().all() else s


_REFRESH = [48]      # samples between repeat alerts while a condition persists (set from the sampling interval in detect())


def _first_runs(mask, min_len: int):
    """Every run of the condition at least min_len long, yielded as (start, end); a long run repeats every 12 h, so a persistent
    fault keeps a fresh alert (the Health Index weakest-link cap only looks at the last 24 h)."""
    for a, b in runs(np.asarray(mask, dtype=bool)):
        if b - a >= min_len:
            for k in range(a, b, max(1, _REFRESH[0])):
                yield k, b


def detect(df: pd.DataFrame, events: pd.DataFrame | None, thresholds: dict) -> list[Alert]:
    df = strip_quarantined(df).reset_index(drop=True)
    if len(df) < 4 or "timestamp" not in df.columns:
        return []
    op = thresholds["operating"]
    ref = thresholds.get("reference", {})
    ts = pd.to_datetime(df["timestamp"])
    h = step_hours(df) or 0.25
    per_h = max(1, int(round(1 / h)))
    _REFRESH[0] = per_h * 12
    sim = lambda i: bool(df["simulated"].iloc[i]) if "simulated" in df.columns else True  # noqa: E731
    out: list[Alert] = []

    # ---- moisture in oil and silica gel (IS 1866 / IEC 60422)
    w = _num(df, "H2O_ppm")
    if w is not None and "moisture_ppm" in op:
        lim = op["moisture_ppm"]
        for a, b_ in _first_runs((w >= lim["watch"]).to_numpy(), 2):
            sev = "critical" if w.iloc[a:b_].max() >= lim["action"] else "warning"
            out.append(make_alert(ts.iloc[a], "moisture_high", sev, "rule", value=w.iloc[a], threshold=lim["watch"],
                                  explanation=f"Moisture in oil {w.iloc[a]:.1f} ppm is above the {lim['watch']:g} ppm watch level "
                                              f"(action level {lim['action']:g} ppm, IS 1866 / IEC 60422). Wet insulation ages faster and "
                                              "lowers the breakdown voltage.", simulated=sim(a)))
    g = _num(df, "SILICA_pct")
    if g is not None and "silica_gel_saturation_pct" in op:
        lim = op["silica_gel_saturation_pct"]["replace"]
        for a, b_ in _first_runs((g >= lim).to_numpy(), 2):
            out.append(make_alert(ts.iloc[a], "silica_gel_exhausted", "warning", "rule", value=g.iloc[a], threshold=lim,
                                  explanation=f"Breather silica gel is {g.iloc[a]:.0f} % saturated (replace at {lim:g} %). "
                                              "Replace or recharge it before moisture reaches the oil.", simulated=sim(a)))

    # ---- winding to tank: earth leakage current
    ie = _num(df, "IEARTH_A")
    irated = ref.get("i_rated_a")
    if ie is not None and irated and "earth_leakage_pct_of_rated" in op:
        lim = op["earth_leakage_pct_of_rated"]
        pct = ie / irated * 100
        for a, b_ in _first_runs((pct >= lim["warning"]).to_numpy(), 2):
            sev = "critical" if pct.iloc[a:b_].max() >= lim["alarm"] else "warning"
            out.append(make_alert(ts.iloc[a], "earth_leakage", sev, "rule", value=ie.iloc[a],
                                  threshold=lim["warning"] / 100 * irated,
                                  explanation=f"Tank earth current {ie.iloc[a]:.1f} A ({pct.iloc[a]:.2f} % of rated). "
                                              "Insulation between a winding and the tank is leaking; a full failure would be an earth fault.",
                                  simulated=sim(a)))

    # ---- turn to turn: winding runs hotter than the twin says while the oil does not
    wti, twin_hs = _num(df, "WTI_C"), _num(df, "twin_hs_C")
    roil = _num(df, "residual_oil_C")
    if wti is not None and twin_hs is not None and "turn_fault" in op:
        lim = op["turn_fault"]
        gap = wti - twin_hs
        oil_ok = (roil.abs() < lim["oil_residual_K"]) if roil is not None else pd.Series(True, index=df.index)
        m = ((gap >= lim["hs_residual_K"]) & oil_ok).to_numpy()
        for a, b_ in _first_runs(m, max(2, int(lim["persist_h"] * per_h))):
            out.append(make_alert(ts.iloc[a], "turn_fault", "critical", "rule", value=gap.iloc[a], threshold=lim["hs_residual_K"],
                                  explanation=f"Winding temperature is {gap.iloc[a]:.1f} K above what the load explains while the oil is normal. "
                                              "That points to shorted turns heating one winding locally.", simulated=sim(a)))

    # ---- charging current: leading kVAr with almost no load
    q, load = _num(df, "Q_kVAr"), _num(df, "loading_pct")
    if q is not None and load is not None and "charging" in op:
        lim = op["charging"]
        kva = (irated or 0) * np.sqrt(3) * thresholds["reference"]["v_ln_nominal_v"] * np.sqrt(3) / 1000 if irated else None
        if kva:
            m = ((q < lim["q_frac_of_rated"] * kva) & (load < lim["max_load_pu"] * 100)).to_numpy()
            for a, b_ in _first_runs(m, 2):
                out.append(make_alert(ts.iloc[a], "charging_current", "info", "rule", value=q.iloc[a],
                                      threshold=lim["q_frac_of_rated"] * kva,
                                      explanation=f"Leading reactive power {q.iloc[a]:.1f} kVAr at {load.iloc[a]:.0f} % load: idle cable or line "
                                                  "capacitance is being charged through the transformer.", simulated=sim(a)))
    
    # ---- efficiency below the loss-based expectation
    eta, eta_ref = _num(df, "eta_pct"), _num(df, "eta_ref_pct")
    if eta is not None and eta_ref is not None and load is not None and "efficiency" in op:
        lim = op["efficiency"]
        m = ((eta_ref - eta >= lim["drop_points"]) & (load >= lim["min_load_pu"] * 100)).to_numpy()
        for a, b_ in _first_runs(m, 4):
            out.append(make_alert(ts.iloc[a], "efficiency_low", "warning", "rule", value=eta.iloc[a], threshold=eta_ref.iloc[a] - lim["drop_points"],
                                  explanation=f"Efficiency {eta.iloc[a]:.2f} % is {eta_ref.iloc[a] - eta.iloc[a]:.2f} points below what the "
                                              "nameplate losses predict at this load: extra loss is being produced inside the unit.", simulated=sim(a)))

    # ---- temperature increase alarm: fast rise of top oil
    oti = _num(df, "OTI_C")
    if oti is not None and "oil_rise_rate_K_per_h" in op:
        lim = op["oil_rise_rate_K_per_h"]["warning"]
        rate = oti.rolling(per_h + 1, min_periods=per_h + 1).apply(lambda x: x.iloc[-1] - x.iloc[0], raw=False)
        for a, b_ in _first_runs((rate >= lim).to_numpy(), 2):
            out.append(make_alert(ts.iloc[a], "temp_rise_fast", "warning", "rule", value=rate.iloc[a], threshold=lim,
                                  explanation=f"Top-oil temperature is climbing {rate.iloc[a]:.1f} K per hour (alarm at {lim:g} K/h).",
                                  simulated=sim(a)))

    # ---- frequency band
    f = _num(df, "freq_Hz")
    if f is not None and "frequency_Hz" in op:
        lim = op["frequency_Hz"]
        m = ((f < lim["low"]) | (f > lim["high"])).to_numpy()
        for a, b_ in _first_runs(m, 2):
            out.append(make_alert(ts.iloc[a], "frequency_off", "warning", "rule", value=f.iloc[a],
                                  threshold=lim["low"] if f.iloc[a] < lim["low"] else lim["high"],
                                  explanation=f"Supply frequency {f.iloc[a]:.2f} Hz is outside {lim['low']:g}-{lim['high']:g} Hz.", simulated=sim(a)))

    # ---- short-circuit trip: a through-fault event big enough to trip protection (IS 2026-5 / IS 1180)
    if events is not None and len(events) and "peak_pu" in events.columns and "short_circuit" in op:
        trip = op["short_circuit"]["trip_pu"]
        for _, e in events[pd.to_numeric(events["peak_pu"], errors="coerce") >= trip].iterrows():
            out.append(make_alert(pd.Timestamp(e["timestamp"]), "short_circuit_trip", "critical", "rule", value=float(e["peak_pu"]),
                                  threshold=trip, explanation=f"Short-circuit current {float(e['peak_pu']):.1f} pu for {float(e.get('duration_ms', 0)):.0f} ms "
                                                              "(trip level {:g} pu). Protection should have operated; check for winding movement.".format(trip),
                                  simulated=bool(e.get("simulated", True))))
    return out
