"""Condition board: one row per quantity an Indian transformer engineer watches, each with its limit and a status.

    board(frame, thresholds, params, asset, events) -> list[dict]
Each item: {id, group, title, value, unit, limit, status ok|watch|alarm|na, detail, standard}.
The numbers come from the live frame (measured + twin) and the limits from config/thresholds.yaml (IS 2026 / IS 1180 /
IS 6600 / IS 1866 / CEA, see the notes there). The silica-gel colour follows the cobalt-chloride indicator (blue when dry,
turning pink as it takes up water); change SILICA_COLOURS if your breather uses a different indicator.
"""
from __future__ import annotations

import math

# (upper saturation %, colour, meaning) for a cobalt-chloride self-indicating gel
SILICA_COLOURS = [(25, "#2F6FD6", "Blue: dry, working"), (50, "#7F5FC4", "Violet: taking up moisture"),
                  (66, "#C45FA8", "Pink-violet: nearly spent"), (101, "#E26BA0", "Pink: saturated, replace")]
INSULATION_LIFE_H = {"normal": 180000.0, "thermally_upgraded": 180000.0}   # IEC 60076-7 normal insulation life


def _f(x, d=math.nan):
    try:
        v = float(x)
        return d if math.isnan(v) else v
    except (TypeError, ValueError):
        return d


def _st(v, watch=None, alarm=None, low=False):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "na"
    if low:
        return "alarm" if alarm is not None and v <= alarm else "watch" if watch is not None and v <= watch else "ok"
    return "alarm" if alarm is not None and v >= alarm else "watch" if watch is not None and v >= watch else "ok"


def silica(pct: float) -> dict:
    for top, colour, label in SILICA_COLOURS:
        if pct < top:
            return {"colour": colour, "label": label}
    return {"colour": SILICA_COLOURS[-1][1], "label": SILICA_COLOURS[-1][2]}


def hot_spot_at(load_pu: float, amb: float, p: dict, cooling: float = 1.0) -> float:
    """Steady-state hot spot (IEC 60076-7): ambient + top-oil rise + gradient."""
    k = max(0.05, cooling)
    top = p["d_theta_or_K"] * ((1 + p["R"] * load_pu ** 2) / (1 + p["R"])) ** p["x"] * k ** -p["x"]
    return amb + top + p["H"] * p["gr_K"] * load_pu ** p["y"]


def load_for_hot_spot(limit_C: float, amb: float, p: dict) -> float | None:
    if hot_spot_at(0.05, amb, p) > limit_C:
        return None
    lo, hi = 0.05, 3.0
    for _ in range(40):
        m = (lo + hi) / 2
        lo, hi = (m, hi) if hot_spot_at(m, amb, p) < limit_C else (lo, m)
    return lo


def board(frame: dict, th: dict, params: dict, asset: dict, events: list[dict] | None = None, rate_K_per_h: float | None = None) -> list[dict]:
    op = th["operating"]
    ref = th["reference"]
    f = frame
    irated = ref["i_rated_a"]
    out: list[dict] = []

    def add(id, group, title, value, unit, limit, status, detail, standard="", scale=None):
        out.append({"id": id, "group": group, "title": title, "value": value, "unit": unit, "limit": limit, "status": status,
                    "detail": detail, "standard": standard, "scale": scale})

    load = _f(f.get("load_pu"), _f(f.get("loading_pct")) / 100)
    amb = _f(f.get("amb_C"))
    oil, wti = _f(f.get("OTI_C")), _f(f.get("WTI_C"))
    hs_twin = _f(f.get("twin_hs_C"))

    # -- faults and loading
    evs = [e for e in (events or []) if _f(e.get("peak_pu"), 0) > 0]
    big = [e for e in evs if _f(e["peak_pu"]) >= op["short_circuit"]["trip_pu"]]
    last = max(evs, key=lambda e: str(e["timestamp"])) if evs else None
    add("short_circuit", "Faults", "Short circuit", _f(last["peak_pu"]) if last else 0.0, "pu peak",
        f"trips above {op['short_circuit']['trip_pu']:g} pu", "alarm" if big else "watch" if evs else "ok",
        (f"{len(evs)} through-fault event(s) logged, {len(big)} at trip level." if evs else "No fault current events."),
        "IS 2026-5 / IS 1180 short-circuit withstand", {"min": 0, "max": 20, "watch": 3, "alarm": op["short_circuit"]["trip_pu"], "dir": "high"})
    ov = op["overcurrent_pu"]["alarm"]
    add("overload", "Loading", "Overload", load, "pu of rating", f"alarm {op['loading_pu']['alarm']:g}, trip {ov:g}",
        _st(load, op["loading_pu"]["warning"], op["loading_pu"]["alarm"]),
        f"Load {load * 100:.0f} % of {asset.get('rating_kVA', '')} kVA ({_f(f.get('I_mean')):.0f} A of {irated:.0f} A).", "IS 6600 loading guide",
        {"min": 0, "max": 1.6, "watch": op["loading_pu"]["warning"], "alarm": op["loading_pu"]["alarm"], "dir": "high"})

    # -- thermal
    hs_lim = op["hot_spot_c"]
    k98 = load_for_hot_spot(hs_lim["warning"], amb, params)
    k120 = load_for_hot_spot(hs_lim["critical"], amb, params)
    add("thermal_capacity", "Thermal", "Thermal capacity left", (k98 if k98 is not None else 0) - load, "pu headroom",
        f"{k98:.2f} pu keeps ageing normal" if k98 is not None else "none at this ambient",
        "alarm" if k98 is not None and load > (k120 or 0) else "watch" if k98 is not None and load > k98 else "ok",
        f"At {amb:.0f} C ambient the unit can carry {k98 if k98 is not None else 0:.2f} pu before the hot spot reaches {hs_lim['warning']:g} C "
        f"and {k120 if k120 is not None else 0:.2f} pu before {hs_lim['critical']:g} C.", "IEC 60076-7 / IS 6600",
        {"min": -0.6, "max": 1.0, "watch": 0.0, "alarm": ((k98 or 0) - (k120 or 0)) if k98 is not None else -0.2, "dir": "low"})
    hs = max(v for v in (wti, hs_twin) if not math.isnan(v)) if not (math.isnan(wti) and math.isnan(hs_twin)) else math.nan
    add("hot_spot", "Thermal", "Hot-spot temperature", hs, "°C", f"{hs_lim['warning']:g} normal ageing / {hs_lim['critical']:g} limit",
        _st(hs, hs_lim["warning"], hs_lim["critical"]), f"Winding sensor {wti:.1f} C, twin {hs_twin:.1f} C.", "IEC 60076-7 / IS 6600",
        {"min": 20, "max": 160, "watch": hs_lim["warning"], "alarm": hs_lim["critical"], "dir": "high"})
    ts = op.get("temperature_settings", {})
    add("temp_alarm", "Thermal", "Temperature alarm", oil, "°C top oil",
        f"alarm {ts.get('oti_alarm_C', 85):g}, trip {ts.get('oti_trip_C', 95):g}; rise rate {op['oil_rise_rate_K_per_h']['warning']:g} K/h",
        "alarm" if oil >= ts.get("oti_trip_C", 95) else "watch" if (oil >= ts.get("oti_alarm_C", 85) or (rate_K_per_h or 0) >= op["oil_rise_rate_K_per_h"]["warning"]) else "ok",
        f"Top oil {oil:.1f} C" + (f", changing {rate_K_per_h:+.1f} K/h." if rate_K_per_h is not None else "."), "OTI / WTI contact settings",
        {"min": 20, "max": 120, "watch": ts.get("oti_alarm_C", 85), "alarm": ts.get("oti_trip_C", 95), "dir": "high"})
    tau, tauw = _f(f.get("tau_oil_min"), params.get("tau_oil_min", 180)), _f(f.get("tau_winding_min"), params.get("tau_winding_min", 4))
    gap = _f(f.get("top_oil_ss_C")) - _f(f.get("twin_oil_C"))
    add("thermal_lag", "Thermal", "Thermal lag", tau / 60, "h oil time constant", f"winding {tauw:.0f} min",
        "ok", f"Oil is {abs(gap):.1f} K {'below' if gap > 0 else 'above'} where this load would settle; it closes about 63 % of that gap every {tau / 60:.1f} h.",
        "IEC 60076-7 exponential model")

    # -- insulation
    gap_w = wti - hs_twin
    tf = op["turn_fault"]
    add("turn_fault", "Insulation", "Turn-to-turn insulation", gap_w, "K winding above twin", f"alarm at {tf['hs_residual_K']:g} K with normal oil",
        _st(gap_w, tf["hs_residual_K"] / 2, tf["hs_residual_K"]), "A shorted turn heats one winding locally while the oil stays normal.", "winding temperature residual",
        {"min": -5, "max": 12, "watch": tf["hs_residual_K"] / 2, "alarm": tf["hs_residual_K"], "dir": "high"})
    ie = _f(f.get("IEARTH_A"), 0.0)
    pct = ie / irated * 100
    el = op["earth_leakage_pct_of_rated"]
    add("tank_insulation", "Insulation", "Winding-to-tank insulation", ie, "A earth current", f"{el['warning']:g} % of rated warns, {el['alarm']:g} % alarms",
        _st(pct, el["warning"], el["alarm"]), f"Earth current is {pct:.2f} % of rated current.", "tank earth monitoring",
        {"min": 0, "max": irated * 0.05, "watch": el["warning"] / 100 * irated, "alarm": el["alarm"] / 100 * irated, "dir": "high"})
    q = _f(f.get("Q_kVAr"))
    kva = float(asset.get("rating_kVA") or irated * math.sqrt(3) * float(asset.get("lv_voltage_V", 415)) / 1000)
    ch = op["charging"]
    add("charging_current", "Electrical", "Charging current (idle conductors)", q, "kVAr", f"leading below {ch['q_frac_of_rated'] * kva:.0f} kVAr at under {ch['max_load_pu'] * 100:.0f} % load",
        "watch" if (q < ch["q_frac_of_rated"] * kva and load < ch["max_load_pu"]) else "ok",
        "Negative reactive power with almost no load means an idle cable or line is being charged." if q < 0 else "Reactive power is inductive (normal).", "")

    # -- voltage
    vn = ref["v_ln_nominal_v"]
    vs = [_f(f.get(c)) / vn for c in ("VR", "VY", "VB")]
    vmax, vmin = max(vs), min(vs)
    band = op["voltage_band_pct"]["limit"] / 100
    worst = vmax if abs(vmax - 1) >= abs(vmin - 1) else vmin
    add("voltage", "Electrical", "Voltage variation", (worst - 1) * 100, "% from nominal", f"±{band * 100:g} %",
        "alarm" if abs(worst - 1) > band else "watch" if abs(worst - 1) > band * 0.7 else "ok",
        f"R {vs[0]:.3f}, Y {vs[1]:.3f}, B {vs[2]:.3f} pu.", "CEA supply voltage variation",
        {"min": -10, "max": 10, "watch": band * 70, "alarm": band * 100, "dir": "band"})

    # -- life
    life_h = INSULATION_LIFE_H.get(str(asset.get("insulation", "normal")), 180000.0)
    used = _f(f.get("days_aged_actual_cum"), _f(f.get("days_aged_cum"), 0.0))
    used_frac = used * 24 / life_h
    rate = _f(f.get("aging_rate_actual"), _f(f.get("aging_rate"), 1.0))
    yrs_now = max(0.0, (life_h - used * 24) / 24 / 365.25 / max(rate, 0.05))
    add("life", "Life", "Life of transformer", (1 - used_frac) * 100, "% insulation life left", f"{life_h / 8766:.1f} years at normal ageing",
        "alarm" if used_frac > 0.9 else "watch" if used_frac > 0.7 else "ok",
        f"Ageing at {rate:.2f}x normal. At this rate about {yrs_now:.1f} years remain (service so far {asset.get('years_in_service', 0)} years).", "IEC 60076-7 / IS 6600",
        {"min": 0, "max": 100, "watch": 30, "alarm": 10, "dir": "low"})

    # -- oil condition
    ppm = _f(f.get("H2O_ppm"))
    mo = op["moisture_ppm"]
    add("moisture", "Oil", "Moisture in oil", ppm, "ppm", f"watch {mo['watch']:g}, action {mo['action']:g}", _st(ppm, mo["watch"], mo["action"]),
        "Water in the oil lowers insulation strength and speeds ageing.", "IS 1866 / IEC 60422",
        {"min": 0, "max": 40, "watch": mo["watch"], "alarm": mo["action"], "dir": "high"})
    g = _f(f.get("SILICA_pct"))
    sc = silica(g if not math.isnan(g) else 0.0)
    add("silica_gel", "Oil", "Silica gel breather", g, "% saturated", f"replace at {op['silica_gel_saturation_pct']['replace']:g} %",
        _st(g, op["silica_gel_saturation_pct"]["replace"] * 0.75, op["silica_gel_saturation_pct"]["replace"]), sc["label"], "cobalt-chloride indicator gel",
        {"min": 0, "max": 100, "watch": op["silica_gel_saturation_pct"]["replace"] * 0.75, "alarm": op["silica_gel_saturation_pct"]["replace"], "dir": "high"})
    out[-1]["colour"] = sc["colour"]

    # -- efficiency
    eta, eref = _f(f.get("eta_pct")), _f(f.get("eta_ref_pct"))
    ef = op["efficiency"]
    add("efficiency", "Efficiency", "Efficiency", eta, "%", f"expected {eref:.2f} % at this load",
        "watch" if (eref - eta >= ef["drop_points"] and load >= ef["min_load_pu"]) else "ok",
        f"Losses {_f(f.get('losses_total_W')) / 1000:.1f} kW: core {_f(f.get('losses_noload_W')) / 1000:.2f} kW, load {_f(f.get('losses_load_W')) / 1000:.1f} kW.",
        "IS 1180 loss levels", {"min": 96, "max": 100, "watch": eref - ef["drop_points"] * 0.5 if eref == eref else None, "alarm": eref - ef["drop_points"] if eref == eref else None, "dir": "low", "ref": eref})
    return out
