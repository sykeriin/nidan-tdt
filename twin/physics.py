"""The physics, made visible (IEC 60076-7 thermal model on any transformer profile).

    steady_chain(asset, load_pu, ambient_C)            load -> top-oil -> hot-spot -> ageing, with the equations
    step_response(asset, from_pu, to_pu, ambient_C)    oil (slow) vs winding hot-spot (fast) after a load step
    whatif(trend, asset, load_mult, ambient_offset_C, rise_mult)    same load history, changed conditions

Everything is computed by the thermal library (the same code the twin runs). steady_chain() also writes out the
closed-form equations with this asset's numbers and checks them against the library's own steady state.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from twin import ageing, detailed, profile, thermal


def _tr(asset: dict, rise_mult: float = 1.0):
    a = profile.complete(asset)
    kw = profile.thermal_kwargs(a)
    kw["top_oil_temp_rise"] = kw.get("top_oil_temp_rise", 60.0) * rise_mult
    return a, thermal.make_transformer(float(a["i_rated_A"]), float(a["load_loss_W"]), float(a["no_load_loss_W"]), **kw)


def steady_chain(asset: dict, load_pu: float, ambient_C: float) -> dict:
    """The calculation chain at a steady load, as ordered steps with formula, numbers and result."""
    if not (0 <= load_pu <= 3):
        raise ValueError("load must be between 0 and 3 per unit")
    a, tr = _tr(asset)
    s = tr.specs
    K = float(load_pu)
    R = s.load_loss / s.no_load_loss
    rated_rise = s.top_oil_temp_rise + s.amb_temp_surcharge
    d_oil = rated_rise * ((1 + R * K ** 2) / (1 + R)) ** s.oil_exp_x
    d_hs = s.hot_spot_fac * s.winding_oil_gradient * K ** s.winding_exp_y
    top, hs = ambient_C + d_oil, ambient_C + d_oil + d_hs
    rate = float(ageing.rate(hs, a.get("insulation", "normal"))[0])

    lib_top, lib_hs = thermal.Stepper(tr).reset(K * float(a["i_rated_A"]), ambient_C)
    f = lambda x, d=1: round(float(x), d)  # noqa: E731
    steps = [
        {"id": "load", "title": "Load", "formula": "K = I / I_rated",
         "working": f"K = {f(K * a['i_rated_A'], 0)} A / {f(a['i_rated_A'], 0)} A", "value": f(K, 2), "unit": "pu",
         "why": "Everything scales with the load as a fraction of the nameplate current."},
        {"id": "losses", "title": "Loss ratio", "formula": "R = P_load / P_no-load",
         "working": f"R = {f(s.load_loss, 0)} W / {f(s.no_load_loss, 0)} W", "value": f(R, 2), "unit": "",
         "why": "Load loss grows with the square of the current; no-load (core) loss does not."},
        {"id": "top_oil", "title": "Top-oil rise over ambient",
         "formula": "Δθ_o = (Δθ_or + Δθ_sur) · ((1 + R·K²) / (1 + R))^x",
         "working": f"({f(s.top_oil_temp_rise)} + {f(s.amb_temp_surcharge)}) · ((1 + {f(R, 2)}·{f(K, 2)}²) / (1 + {f(R, 2)}))^{f(s.oil_exp_x, 2)}",
         "value": f(d_oil), "unit": "K",
         "why": "Heat the oil must shed: losses at this load against losses at rated load, shaped by the oil exponent x."},
        {"id": "gradient", "title": "Hot-spot rise over top oil", "formula": "Δθ_h = H · g_r · K^y",
         "working": f"{f(s.hot_spot_fac, 2)} · {f(s.winding_oil_gradient)} · {f(K, 2)}^{f(s.winding_exp_y, 2)}",
         "value": f(d_hs), "unit": "K", "why": "The winding runs hotter than the oil around it, and that gap grows faster than the load."},
        {"id": "hot_spot", "title": "Hot-spot temperature", "formula": "θ_h = θ_a + Δθ_o + Δθ_h",
         "working": f"{f(ambient_C)} + {f(d_oil)} + {f(d_hs)}", "value": f(hs), "unit": "°C",
         "why": "Where the insulation is under the most thermal stress."},
        {"id": "ageing", "title": "Insulation ageing rate", "formula": "V = 2^((θ_h − 98) / 6)",
         "working": f"2^(({f(hs)} − 98) / 6)", "value": f(rate, 3), "unit": "× normal",
         "why": "Paper life halves for every 6 K above 98 °C (normal Kraft paper). 1 means ageing exactly as designed."},
    ]
    return {
        "steps": steps,
        "inputs": {"load_pu": f(K, 3), "ambient_C": f(ambient_C), "current_A": f(K * a["i_rated_A"], 0)},
        "top_oil_C": f(top), "hot_spot_C": f(hs), "ageing_rate": f(rate, 4),
        "hours_per_equivalent_day": f(24 / rate, 1) if rate > 0 else None,
        "library_check": {"top_oil_C": f(lib_top, 3), "hot_spot_C": f(lib_hs, 3),
                          "max_abs_diff_K": f(max(abs(lib_top - top), abs(lib_hs - hs)), 4),
                          "note": "Equations above vs the thermal library's own steady state."},
        "parameters": {"top_oil_rise_K": f(s.top_oil_temp_rise), "amb_temp_surcharge_K": f(s.amb_temp_surcharge),
                       "winding_oil_gradient_K": f(s.winding_oil_gradient), "hot_spot_factor": f(s.hot_spot_fac, 2),
                       "oil_exponent_x": f(s.oil_exp_x, 2), "winding_exponent_y": f(s.winding_exp_y, 2),
                       "load_loss_W": f(s.load_loss, 0), "no_load_loss_W": f(s.no_load_loss, 0)},
        "tags": a.get("tags", {}),
    }


def step_response(asset: dict, from_pu: float, to_pu: float, ambient_C: float, minutes: int = 480) -> dict:
    """Top-oil and hot-spot after an instant change of load, one-minute steps."""
    if not (0 <= from_pu <= 3 and 0 <= to_pu <= 3):
        raise ValueError("loads must be between 0 and 3 per unit")
    if not (10 <= minutes <= 2880):
        raise ValueError("minutes must be between 10 and 2880")
    a, tr = _tr(asset)
    i_rated = float(a["i_rated_A"])
    st = thermal.Stepper(tr)
    st.reset(from_pu * i_rated, ambient_C)
    t, oil, hs = [0], [], []
    o0, h0 = st.reset(from_pu * i_rated, ambient_C)
    oil.append(o0), hs.append(h0)
    for m in range(1, minutes + 1):
        o, h = st.step(to_pu * i_rated, ambient_C, 1.0)
        t.append(m), oil.append(float(o)), hs.append(float(h))
    final_o, final_h = thermal.Stepper(tr).reset(to_pu * i_rated, ambient_C)
    s = tr.specs
    return {"t_min": t, "top_oil_C": [round(x, 2) for x in oil], "hot_spot_C": [round(x, 2) for x in hs],
            "final": {"top_oil_C": round(float(final_o), 2), "hot_spot_C": round(float(final_h), 2)},
            "time_constants_min": {"oil": float(s.time_const_oil), "winding": float(s.time_const_windings)},
            "inputs": {"from_pu": from_pu, "to_pu": to_pu, "ambient_C": ambient_C}}


def _segments(ts: pd.Series, valid: np.ndarray, gap_h: float = 2.0):
    vi = np.flatnonzero(valid)
    if not len(vi):
        return []
    gaps = ts.iloc[vi].reset_index(drop=True).diff()
    starts = np.r_[0, np.flatnonzero((gaps > pd.Timedelta(hours=gap_h)).to_numpy())]
    ends = np.r_[starts[1:], len(vi)]
    return [vi[s0:s1] for s0, s1 in zip(starts, ends)]


def _run(trend: pd.DataFrame, tr, insulation: str, load_mult: float, amb_offset: float, model: str = "iec",
         asset: dict | None = None, rise_mult: float = 1.0, k_factor: float = 1.0) -> pd.DataFrame:
    amps = trend["I_mean"].to_numpy(float) * load_mult
    amb = trend["amb_C"].to_numpy(float) + amb_offset
    ts = trend["timestamp"]
    n = len(trend)
    oil, hs = np.full(n, np.nan), np.full(n, np.nan)
    dm = detailed.DetailedModel(asset) if model == "detailed" else None
    for rows in _segments(ts, ~np.isnan(amps) & ~np.isnan(amb)):
        if dm is not None:
            seg_dt = ts.iloc[rows].diff().dt.total_seconds().fillna(0.0).to_numpy() / 60.0
            out = dm.simulate(amps[rows], amb[rows], seg_dt, float(asset["i_rated_A"]), rise_mult, None, k_factor)
            oil[rows], hs[rows] = out["top_oil_C"], out["hot_spot_C"]
        else:
            oil[rows], hs[rows] = thermal.run_segment(tr, ts.iloc[rows], amps[rows], amb[rows])
    dt = ts.diff().dt.total_seconds().fillna(0).to_numpy() / 60
    dt[dt > 120] = 0                                  # a long gap is not time spent ageing
    rate = np.full(n, np.nan)
    ok = ~np.isnan(hs)
    if ok.any():
        rate[ok] = ageing.rate(hs[ok], insulation)
    return pd.DataFrame({"timestamp": ts, "top_oil_C": oil, "hot_spot_C": hs, "ageing_rate": rate, "dt_min": dt})


def whatif(trend: pd.DataFrame, asset: dict, load_mult: float = 1.0, ambient_offset_C: float = 0.0,
           rise_mult: float = 1.0, reference_life_h: float = 180000.0, model: str = "iec",
           k_factor: float = 1.0) -> tuple[pd.DataFrame, dict]:
    """Replay the same load and weather history under changed conditions. Returns (series, summary).

    series columns: timestamp, base_*, whatif_* for top_oil_C, hot_spot_C, ageing_rate.
    rise_mult > 1 models degraded cooling (a larger top-oil rise), as in scenario S2.
    """
    if not (0.2 <= load_mult <= 2.0):
        raise ValueError("load multiplier must be between 0.2 and 2.0")
    if not (-15 <= ambient_offset_C <= 25):
        raise ValueError("ambient offset must be between -15 and 25 °C")
    if not (0.7 <= rise_mult <= 2.0):
        raise ValueError("cooling (rise) multiplier must be between 0.7 and 2.0")
    if model not in ("iec", "detailed"):
        raise ValueError("model must be 'iec' or 'detailed'")
    if not (1.0 <= k_factor <= 20.0):
        raise ValueError("K-factor must be between 1 and 20")
    if k_factor != 1.0 and model != "detailed":
        raise ValueError("harmonic (K-factor) loss needs the detailed model")
    need = {"timestamp", "I_mean", "amb_C"}
    if not need <= set(trend.columns):
        raise ValueError("this dataset has no time series of load and ambient temperature to replay")
    a, tr0 = _tr(asset)
    _, tr1 = _tr(asset, rise_mult)
    ins = a.get("insulation", "normal")
    base = _run(trend, tr0, ins, 1.0, 0.0, model, a, 1.0, 1.0)
    alt = _run(trend, tr1, ins, load_mult, ambient_offset_C, model, a, rise_mult, k_factor)

    def summary(df):
        hours = float(df["dt_min"].sum() / 60)
        days = float((df["ageing_rate"].fillna(0) * df["dt_min"]).sum() / 1440)
        mean_rate = days * 24 / hours if hours > 0 else float("nan")
        return {"peak_top_oil_C": round(float(df["top_oil_C"].max()), 1), "peak_hot_spot_C": round(float(df["hot_spot_C"].max()), 1),
                "hours_hot_spot_above_98C": round(float(df.loc[df["hot_spot_C"] > 98, "dt_min"].sum() / 60), 1),
                "mean_ageing_rate": round(mean_rate, 4), "equivalent_days_used": round(days, 3),
                "window_days": round(hours / 24, 1),
                "years_to_reference_life_at_this_rate": round(reference_life_h / 24 / 365.25 / mean_rate, 1) if mean_rate and mean_rate > 0 else None}

    out = pd.DataFrame({"timestamp": base["timestamp"],
                        "base_top_oil_C": base["top_oil_C"], "base_hot_spot_C": base["hot_spot_C"], "base_ageing_rate": base["ageing_rate"],
                        "whatif_top_oil_C": alt["top_oil_C"], "whatif_hot_spot_C": alt["hot_spot_C"], "whatif_ageing_rate": alt["ageing_rate"]})
    return out, {"base": summary(base), "whatif": summary(alt),
                 "inputs": {"load_mult": load_mult, "ambient_offset_C": ambient_offset_C, "rise_mult": rise_mult, "model": model, "k_factor": k_factor},
                 "note": "Thermal ageing only (" + ("IEC 60076-7 thermal model" if model == "iec" else "detailed heat-balance model") + ", normal paper). A comparison of the same history, not a prediction."}


# ---------------------------------------------------------------- two models, one step
def _loss_row(L: dict) -> dict:
    row = {k: round(float(L[k]), 0) for k in ("core", "i2r", "eddy", "stray", "total")}
    row["winding_temp_C"] = round(float(L["winding_temp_C"]), 1)
    return row


def compare_models(asset: dict, from_pu: float, to_pu: float, ambient_C: float, minutes: int = 600,
                   k_factor: float = 1.0, use_mass_capacity: bool = False) -> dict:
    """The standard IEC model and the detailed heat-balance model on the same load step, plus the loss breakdown."""
    if not (0 <= from_pu <= 3 and 0 <= to_pu <= 3):
        raise ValueError("loads must be between 0 and 3 per unit")
    if not (10 <= minutes <= 2880):
        raise ValueError("minutes must be between 10 and 2880")
    if not (1.0 <= k_factor <= 20.0):
        raise ValueError("K-factor must be between 1 and 20")
    a = profile.complete(asset)
    iec = step_response(a, from_pu, to_pu, ambient_C, minutes)
    i_rated = float(a["i_rated_A"])
    dm = detailed.DetailedModel(a, use_mass_capacity)
    n = minutes + 1
    out = dm.simulate(np.r_[from_pu, np.full(n - 1, to_pu)] * i_rated, ambient_C, np.r_[0.0, np.ones(n - 1)], i_rated, 1.0, None, k_factor)
    t = np.arange(n)
    r2 = lambda x: [round(float(v), 2) for v in x]  # noqa: E731
    o0, h0, L0 = dm.steady_state(from_pu, ambient_C, 1.0, k_factor)
    o1, h1, L1 = dm.steady_state(to_pu, ambient_C, 1.0, k_factor)
    iec_o, iec_h = thermal.Stepper(_tr(a)[1]).reset(to_pu * i_rated, ambient_C)
    return {
        "t_min": [int(x) for x in t], "iec": {"top_oil_C": iec["top_oil_C"], "hot_spot_C": iec["hot_spot_C"]},
        "detailed": {"top_oil_C": r2(out["top_oil_C"]), "hot_spot_C": r2(out["hot_spot_C"])},
        "steady_after": {"iec": {"top_oil_C": round(float(iec_o), 1), "hot_spot_C": round(float(iec_h), 1)},
                         "detailed": {"top_oil_C": round(o1, 1), "hot_spot_C": round(h1, 1)}},
        "losses": {"before": _loss_row(L0), "after": _loss_row(L1)},
        "viscosity": {"oil_at_rated_C": round(dm.theta_oil_rated, 1),
                      "ratio_before": round(float(detailed._nu(o0) / dm.nu_rated), 2),
                      "ratio_after": round(float(detailed._nu(o1) / dm.nu_rated), 2),
                      "note": "Oil viscosity relative to its value at rated conditions. Thicker oil widens the winding-to-oil gradient."},
        "time_constants": {"iec_nominal_min": iec["time_constants_min"]["oil"],
                           "iec_63pct_min": detailed.effective_time_constant_min(t, iec["top_oil_C"], iec["top_oil_C"][0], iec["top_oil_C"][-1]),
                           "detailed_63pct_min": detailed.effective_time_constant_min(t, out["top_oil_C"], out["top_oil_C"][0], out["top_oil_C"][-1]),
                           "implied_by_masses": detailed.implied_time_constant_h(a)},
        "inputs": {"from_pu": from_pu, "to_pu": to_pu, "ambient_C": ambient_C, "k_factor": k_factor, "use_mass_capacity": use_mass_capacity},
        "assumptions": {"loss_split": detailed.LOSS_SPLIT, "viscosity_constant_K": detailed.VISC_D, "gradient_viscosity_exponent": detailed.VISC_EXP,
                        "note": "Loss split, viscosity law and exponents are textbook or modelling choices (tagged assumed), not measured for this unit."},
    }
