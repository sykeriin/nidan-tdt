"""Per-part view of the twin at one instant, for the 3D callouts and pinned section panels.

For every inspectable part: its live quantities (measured / twin / residual, with unit and an estimated flag),
its governing equation(s) with every term and the result as numbers plus a ready-made substituted string, the
alerts active on it (last 24 h) and the recommended tests. The dashboard renders this; it computes nothing.

Part ids match web/src/twin/parts.ts.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

PHASES = ("R", "Y", "B")
PART_IDS = ("tank", "oil", "core", "winding-R", "winding-Y", "winding-B", "radiators", "conservator", "oil-gauge",
            "breather", "hv-bushings", "lv-R", "lv-Y", "lv-B", "lv-N", "cts", "oti", "ambient", "nameplate")

# alert type -> parts it is drawn on (asset-origin findings)
TYPE_PARTS: dict[str, tuple[str, ...]] = {
    "loading_high": ("winding-R", "winding-Y", "winding-B", "cts"),
    "overcurrent": ("winding-R", "winding-Y", "winding-B", "cts"),
    "hot_spot_high": ("winding-R", "winding-Y", "winding-B"),
    "ageing_rate_high": ("winding-R", "winding-Y", "winding-B"),
    "top_oil_high": ("oil", "tank", "oti"),
    "residual_drift": ("radiators", "oil"),
    "current_unbalance": ("lv-R", "lv-Y", "lv-B", "lv-N"),
    "voltage_unbalance": ("lv-R", "lv-Y", "lv-B", "hv-bushings"),
    "voltage_high": ("lv-R", "lv-Y", "lv-B", "hv-bushings"),
    "voltage_low": ("lv-R", "lv-Y", "lv-B", "hv-bushings"),
    "oil_low": ("conservator", "oil-gauge"),
    "oil_leak": ("conservator", "oil-gauge", "tank"),
    "oil_theft": ("conservator", "oil-gauge"),
    "through_fault": ("winding-R", "winding-Y", "winding-B"),
    "through_fault_stress": ("winding-R", "winding-Y", "winding-B"),
    "implausible_sensor": ("oti",),
}
# sensor channel (suffix of a sensor alert id) -> the device on the model
CHANNEL_PARTS: dict[str, tuple[str, ...]] = {
    "OTI_C": ("oti",), "WTI_C": ("winding-R", "winding-Y", "winding-B"), "ATI_C": ("ambient",),
    "amb_C": ("ambient",), "OLI_pct": ("oil-gauge",), "RH_pct": ("breather",), "IN": ("lv-N",),
    **{f"I{p}": ("cts", f"lv-{p}") for p in PHASES}, **{f"V{p}": (f"lv-{p}",) for p in PHASES},
}


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _f(v, d: int = 1) -> str:
    return "—" if v is None else f"{v:.{d}f}"


def q(key: str, label: str, value, unit: str, kind: str, estimated: bool = False, digits: int = 1) -> dict:
    """One quantity. kind: measured | twin | residual | info."""
    return {"key": key, "label": label, "value": _num(value), "unit": unit, "kind": kind, "estimated": estimated,
            "digits": digits}


def term(symbol: str, value, unit: str, meaning: str, estimated: bool = False, digits: int = 2) -> dict:
    return {"symbol": symbol, "value": _num(value), "unit": unit, "meaning": meaning, "estimated": estimated,
            "digits": digits}


def eq(name: str, symbolic: str, substituted: str, result_symbol: str, result, unit: str, terms: list[dict],
       note: str | None = None, estimated: bool = False, digits: int = 2) -> dict:
    ok = all(t["value"] is not None for t in terms) and _num(result) is not None
    return {"name": name, "symbolic": symbolic, "substituted": substituted if ok else None,
            "result": {"symbol": result_symbol, "value": _num(result) if ok else None, "unit": unit, "digits": digits},
            "terms": terms, "note": note if ok else "not available at this instant: an input is missing",
            "estimated": estimated}


def parts_for_alert(a) -> tuple[str, ...]:
    if a.origin == "sensor":
        for ch, parts in CHANNEL_PARTS.items():
            if a.id.endswith("-" + ch):
                return parts
    return TYPE_PARTS.get(a.type, ())


def build(row: dict, prof: dict, p: dict, asset: dict, mode: str, alerts: list, recs: list,
          oti_suspect: bool = False) -> dict[str, dict]:
    """row: run.trend row; prof: twin/profile.py columns at the same row; p: profile.params();
    oti_suspect: the run-level plausibility verdict for OTI_C."""
    g = lambda k: _num(row.get(k))
    meter_only = mode == "meter_only"
    K, amb = g("load_pu"), g("amb_C")
    oil_t, hs_t, oti = g("twin_oil_C"), g("twin_hs_C"), None if meter_only else g("OTI_C")
    hs_age, src = g("hs_ageing_C"), str(row.get("ageing_source") or "")
    i_r = p["I_rated_A"]
    pr = {k: _num(v) for k, v in prof.items()}
    est_losses = True  # load / no-load losses are placeholder nameplate values (asset.yaml) or scaled from them
    out: dict[str, dict] = {pid: {"quantities": [], "equations": [], "alerts": [], "tests": []} for pid in PART_IDS}

    # ---- oil / tank: top-oil steady state and approach with tau_oil
    top_ss = pr.get("top_oil_ss_C")
    ratio = None if K is None else (1 + p["R"] * K ** 2) / (1 + p["R"])
    top_eq = eq("Top-oil temperature, steady state (IEC 60076-7)",
                "θo,ss = θa + Δθor·((1 + R·K²)/(1 + R))^x",
                f"θo,ss = {_f(amb)} + {_f(p['d_theta_or_K'], 0)} × ((1 + {_f(p['R'])} × {_f(K, 2)}²)/(1 + {_f(p['R'])}))^{_f(p['x'], 1)}"
                f" = {_f(top_ss)} °C",
                "θo,ss", top_ss, "°C",
                [term("θa", amb, "°C", "ambient air", digits=1), term("Δθor", p["d_theta_or_K"], "K", "rated top-oil rise (incl. ambient surcharge)", digits=0),
                 term("R", p["R"], "", "load loss / no-load loss", estimated=est_losses),
                 term("K", K, "pu", "load factor I/I_rated"), term("x", p["x"], "", "oil exponent (ONAN)", digits=1)],
                note="the twin's top-oil moves toward this value with time constant τo")
    rate = None if top_ss is None or oil_t is None else (top_ss - oil_t) / p["tau_oil_min"]
    lag_eq = eq("Top-oil approach (first-order lag)", "dθo/dt = (θo,ss − θo)/τo",
                f"dθo/dt = ({_f(top_ss)} − {_f(oil_t)})/{_f(p['tau_oil_min'], 0)} = {_f(rate, 3)} K/min",
                "dθo/dt", rate, "K/min",
                [term("θo,ss", top_ss, "°C", "steady-state top-oil", digits=1), term("θo", oil_t, "°C", "twin top-oil now", digits=1),
                 term("τo", p["tau_oil_min"], "min", "oil time constant", digits=0)], digits=3)
    oil_q = [q("OTI_C", "top-oil", oti, "°C", "measured"), q("twin_oil_C", "top-oil", oil_t, "°C", "twin"),
             q("residual_oil_C", "measured − twin", None if meter_only else row.get("residual_oil_C"), "K", "residual"),
             q("bottom_oil_C", "bottom oil", pr.get("bottom_oil_C"), "°C", "twin", estimated=True),
             q("top_oil_ss_C", "top-oil, steady state", top_ss, "°C", "twin"),
             q("oil_flow_intensity", "oil flow (1 = full)", pr.get("oil_flow_intensity"), "", "twin", estimated=True, digits=2)]
    out["oil"].update(quantities=oil_q, equations=[top_eq, lag_eq])
    stored = pr.get("heat_stored_W")
    out["tank"].update(quantities=oil_q[:3] + [q("heat_stored_W", "heat stored in oil and steel", stored, "W", "twin", estimated=True, digits=0)],
                       equations=[eq("Energy balance", "P_stored = P_losses − Q_out",
                                     f"P_stored = {_f(pr.get('losses_total_W'), 0)} − {_f(pr.get('heat_dissipated_W'), 0)} = {_f(stored, 0)} W",
                                     "P_stored", stored, "W",
                                     [term("P_losses", pr.get("losses_total_W"), "W", "no-load + load loss", True, 0),
                                      term("Q_out", pr.get("heat_dissipated_W"), "W", "heat leaving to air", True, 0)],
                                     note="> 0: oil heating up; < 0: cooling down", estimated=True, digits=0)])

    # ---- core: no-load loss
    p0, pl, pt = pr.get("losses_noload_W"), pr.get("losses_load_W"), pr.get("losses_total_W")
    out["core"].update(
        quantities=[q("losses_noload_W", "no-load loss", p0, "W", "twin", estimated=True, digits=0),
                    q("load_pu", "load factor K", K, "pu", "twin", digits=2)],
        equations=[eq("Total losses", "P = P0 + Pk·K²",
                      f"P = {_f(p['P0_W'], 0)} + {_f(p['Pk_W'], 0)} × {_f(K, 2)}² = {_f(pt, 0)} W", "P", pt, "W",
                      [term("P0", p["P0_W"], "W", "no-load (core) loss, constant while energised", True, 0),
                       term("Pk", p["Pk_W"], "W", "load loss at rated current", True, 0), term("K", K, "pu", "load factor")],
                      note="core loss is constant; winding loss grows with K²", estimated=True, digits=0)])

    # ---- windings, per phase
    for ph in PHASES:
        i_ph = g(f"I{ph}")
        k_ph = None if i_ph is None else i_ph / i_r
        grad = None if k_ph is None else p["H"] * p["gr_K"] * k_ph ** p["y"]
        v = g("aging_rate_actual")
        pid = f"winding-{ph}"
        theta_label = "measured oil + twin gradient" if src == "measured" else "twin"
        out[pid].update(
            quantities=[q(f"I{ph}", "phase current", i_ph, "A", "measured", digits=0),
                        q(f"K_{ph}", "phase load factor", k_ph, "pu", "measured", digits=2),
                        q("twin_hs_C", "hot-spot", hs_t, "°C", "twin"),
                        q("hs_ageing_C", "hot-spot, for ageing", hs_age, "°C", "measured" if src == "measured" else "twin"),
                        q("WTI_C", "winding indicator", None if meter_only else row.get("WTI_C"), "°C", "measured"),
                        q("avg_winding_C", "average winding", pr.get("avg_winding_C"), "°C", "twin", estimated=True),
                        q("aging_rate_actual", "ageing rate", v, "× normal", "twin", digits=2),
                        q("days_aged_actual_cum", "life used this period", row.get("days_aged_actual_cum"), "days", "twin", digits=2)],
            equations=[
                eq("Insulation ageing rate (IEC 60076-7, normal paper)", "V = 2^((θh − 98)/6)",
                   f"V = 2^(({_f(hs_age)} − 98)/6) = {_f(v, 2)} × normal ageing", "V", v, "× normal",
                   [term("θh", hs_age, "°C", f"hot-spot, {theta_label}", digits=1)],
                   note="every 6 K above 98 °C doubles the rate at which the paper ages"),
                eq(f"Hot-spot rise over top-oil, phase {ph} (steady state)", "Δθh = H·gr·K^y",
                   f"Δθh = {_f(p['H'], 1)} × {_f(p['gr_K'], 0)} × {_f(k_ph, 2)}^{_f(p['y'], 1)} = {_f(grad)} K", "Δθh", grad, "K",
                   [term("H", p["H"], "", "hot-spot factor", digits=1), term("gr", p["gr_K"], "K", "rated winding-oil gradient", digits=0),
                    term("K", k_ph, "pu", f"phase {ph} load factor"), term("y", p["y"], "", "winding exponent", digits=1)],
                   note="the twin's dynamic gradient lags this with τw", digits=1),
            ])

    # ---- radiators: heat out and effectiveness
    q_out, k_rad = pr.get("heat_dissipated_W"), pr.get("radiator_effectiveness")
    rise_t = None if oil_t is None or amb is None else oil_t - amb
    rise_m = None if oti is None or amb is None else oti - amb
    rad_eqs = [eq("Heat to air (inverse of the steady-state top-oil law)", "Q_out = (P0 + Pk)·(Δθo/Δθor)^(1/x)",
                  f"Q_out = {_f(p['P0_W'] + p['Pk_W'], 0)} × ({_f(rise_t)}/{_f(p['d_theta_or_K'], 0)})^(1/{_f(p['x'], 1)}) = {_f(q_out, 0)} W",
                  "Q_out", q_out, "W",
                  [term("P0 + Pk", p["P0_W"] + p["Pk_W"], "W", "losses at rated load", True, 0),
                   term("Δθo", rise_t, "K", "twin top-oil rise over ambient", digits=1),
                   term("Δθor", p["d_theta_or_K"], "K", "rated top-oil rise", digits=0), term("x", p["x"], "", "oil exponent", digits=1)],
                  estimated=True, digits=0)]
    if not meter_only:
        rad_eqs.append(eq("Cooling effectiveness (share of nominal radiator capacity)", "k = (Δθo,twin/Δθo,meas)^(1/x)",
                          f"k = ({_f(rise_t)}/{_f(rise_m)})^(1/{_f(p['x'], 1)}) ≈ {_f(k_rad, 2)} (6 h median)", "k", k_rad, "",
                          [term("Δθo,twin", rise_t, "K", "rise a healthy radiator bank gives", digits=1),
                           term("Δθo,meas", rise_m, "K", "measured rise", digits=1), term("x", p["x"], "", "oil exponent", digits=1)],
                          note="1 = radiators as designed; below 1 the oil runs hotter than physics predicts",
                          estimated=True))
    out["radiators"].update(
        quantities=[q("amb_C", "ambient air", amb, "°C", "measured"),
                    q("heat_dissipated_W", "heat to air", q_out, "W", "twin", estimated=True, digits=0),
                    q("radiator_effectiveness", "cooling effectiveness", k_rad, "", "twin", estimated=True, digits=2),
                    q("oil_flow_intensity", "oil flow (1 = full)", pr.get("oil_flow_intensity"), "", "twin", estimated=True, digits=2)],
        equations=rad_eqs)

    # ---- sensors
    lo, hi = g("rise_low_K"), g("rise_high_K")
    where = (None if rise_m is None or lo is None or hi is None
             else "below" if rise_m < lo else "above" if rise_m > hi else "inside")
    # Below the band is impossible for any healthy or faulty unit: the sensor. Above it is either a cooling fault or
    # the sensor; the run-level verdict (share of out-of-band rows, twin/plausibility.py) tells them apart.
    note = {"inside": None,
            "below": "SUSPECT: cooler than physics allows; check the device, not the transformer",
            "above": ("SUSPECT: far outside physics for the whole record; check the device, not the transformer"
                      if oti_suspect else "hotter than a healthy unit at this load: cooling fault or sensor; "
                      "compare with the radiator effectiveness")}.get(where)
    shown = {"inside": f"{_f(lo)} ≤ {_f(rise_m)} ≤ {_f(hi)} K: inside the band",
             "below": f"{_f(rise_m)} < {_f(lo)} K: below the band",
             "above": f"{_f(rise_m)} > {_f(hi)} K: above the band"}.get(where, "")
    out["oti"].update(
        quantities=[q("OTI_C", "top-oil reading", oti, "°C", "measured"), q("twin_oil_C", "top-oil", oil_t, "°C", "twin"),
                    q("rise_low_K", "possible rise, low", lo, "K", "twin"), q("rise_high_K", "possible rise, high", hi, "K", "twin")],
        equations=[] if meter_only else [eq("Physics plausibility band", "Δθ_low ≤ OTI − θa ≤ Δθ_high",
                   f"OTI − θa = {_f(oti)} − {_f(amb)} = {_f(rise_m)} K;  {shown}", "OTI − θa", rise_m, "K",
                   [term("Δθ_low", lo, "K", "rise of the coolest plausible oil-immersed unit", digits=1),
                    term("OTI", oti, "°C", "reading", digits=1), term("θa", amb, "°C", "ambient", digits=1),
                    term("Δθ_high", hi, "K", "rise of the hottest plausible unit", digits=1)],
                   note=note, digits=1)])
    out["oti"]["verdict"] = None if meter_only else ("suspect" if oti_suspect or where == "below" else where)
    out["ambient"]["quantities"] = [q("amb_C", "ambient air", amb, "°C", "measured"),
                                    q("ATI_C", "ambient indicator", row.get("ATI_C"), "°C", "measured")]
    out["breather"]["quantities"] = [q("RH_pct", "air humidity", row.get("RH_pct"), "%", "measured", digits=0)]
    for pid in ("conservator", "oil-gauge"):
        out[pid]["quantities"] = [q("OLI_pct", "oil level", row.get("OLI_pct"), "%", "measured")]

    # ---- electrical: bushings and CTs
    for ph in PHASES:
        i_ph = g(f"I{ph}")
        k_ph = None if i_ph is None else i_ph / i_r
        out[f"lv-{ph}"].update(
            quantities=[q(f"V{ph}", "phase voltage", row.get(f"V{ph}"), "V", "measured"),
                        q(f"I{ph}", "phase current", i_ph, "A", "measured", digits=0),
                        q(f"K_{ph}", "phase load factor", k_ph, "pu", "measured", digits=2)],
            equations=[eq(f"Load factor, phase {ph}", "K = I / I_rated", f"K = {_f(i_ph, 0)} / {_f(i_r, 0)} = {_f(k_ph, 2)} pu",
                          "K", k_ph, "pu", [term("I", i_ph, "A", f"phase {ph} current", digits=0),
                                            term("I_rated", i_r, "A", "rated LV current", digits=0)])])
    i_m, i_n = g("I_mean"), g("IN")
    n_pct = None if i_m in (None, 0) or i_n is None else 100 * i_n / i_m
    out["lv-N"]["quantities"] = [q("IN", "neutral current", i_n, "A", "measured"),
                                 q("IN_pct", "neutral / mean phase current", n_pct, "%", "measured")]
    out["cts"].update(
        quantities=[q(f"I{ph}", f"current {ph}", row.get(f"I{ph}"), "A", "measured", digits=0) for ph in PHASES]
        + [q("I_mean", "mean current", i_m, "A", "measured", digits=0)],
        equations=[eq("Mean phase current (drives the twin)", "I = (I_R + I_Y + I_B)/3",
                      f"I = ({_f(g('IR'), 0)} + {_f(g('IY'), 0)} + {_f(g('IB'), 0)})/3 = {_f(i_m, 0)} A", "I", i_m, "A",
                      [term(f"I_{ph}", g(f"I{ph}"), "A", f"phase {ph}", digits=0) for ph in PHASES], digits=0)])
    s_kva = g("S_kVA")
    hv_v = _num(asset.get("hv_voltage_V"))
    i_hv = None if s_kva is None or not hv_v else s_kva * 1000 / (math.sqrt(3) * hv_v)
    out["hv-bushings"].update(
        quantities=[q("I_HV", "HV line current", i_hv, "A", "twin", estimated=True, digits=2)],
        equations=[] if not hv_v else [eq("HV current from LV apparent power (HV side not metered)", "I_HV = S/(√3·V_HV)",
                   f"I_HV = {_f(s_kva)} kVA/(√3 × {_f(hv_v / 1000, 0)} kV) = {_f(i_hv, 2)} A", "I_HV", i_hv, "A",
                   [term("S", s_kva, "kVA", "apparent power, LV side", digits=1),
                    term("V_HV", hv_v, "V", "HV line voltage (nameplate)", True, 0)], estimated=True)])
    kva = _num(asset.get("rating_kVA"))
    lv = _num(asset.get("lv_voltage_V"))
    out["nameplate"].update(
        quantities=[q("rating_kVA", "rating", kva, "kVA", "info", estimated=asset.get("nameplate_source") == "estimated", digits=0),
                    q("I_rated_A", "rated LV current", i_r, "A", "info", digits=0),
                    q("load_loss_W", "load loss", p["Pk_W"], "W", "info", estimated=True, digits=0),
                    q("no_load_loss_W", "no-load loss", p["P0_W"], "W", "info", estimated=True, digits=0)],
        equations=[] if not (kva and lv) else [eq("Rated LV current", "I_rated = S/(√3·V_LV)",
                   f"I_rated = {_f(kva, 0)} kVA/(√3 × {_f(lv, 0)} V) = {_f(kva * 1000 / (math.sqrt(3) * lv), 0)} A", "I_rated",
                   kva * 1000 / (math.sqrt(3) * lv), "A",
                   [term("S", kva, "kVA", "rating", digits=0), term("V_LV", lv, "V", "LV line voltage", digits=0)], digits=0)])

    # ---- findings on parts
    rec_by_alert = {r.alert_id: r for r in recs}
    for a in alerts:
        r = rec_by_alert.get(a.id)
        for pid in parts_for_alert(a):
            out[pid]["alerts"].append({"id": a.id, "type": a.type, "severity": a.severity, "origin": a.origin,
                                       "timestamp": a.timestamp, "explanation": a.explanation})
            if r and r.test and r.test not in out[pid]["tests"]:
                out[pid]["tests"].append(r.test)
    return out
