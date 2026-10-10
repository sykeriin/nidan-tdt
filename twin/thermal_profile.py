"""Thermal profile of the twin at each row (IEC 60076-7 thermal diagram), for the 3D view and the what-if panel.

Everything is derived from the twin's own parameters (the library's TransformerSpecifications built from asset.yaml)
and the twin's computed temperatures; nothing new is fitted.

    K          = I_mean / I_rated
    losses     P0 (no-load, constant, core) + Pk·K² (load, windings)                 [est.: placeholder nameplate]
    top-oil ss θa + Δθor·((1 + R·K²)/(1 + R))^x,   R = Pk/P0                           (library _end_temperature_top_oil)
    hot-spot   θo + H·gr·K^y at steady state; the twin's dynamic value otherwise
    bottom oil θa + β·(θo − θa)                                                       [est.: β from twin.yaml]
    avg oil    (θo + θb)/2;  avg winding = avg oil + gr·K^y                           [est.]
    heat out   (P0 + Pk)·(Δθo/Δθor)^(1/x): the loss whose steady-state rise equals the present rise
    stored     P_total − heat out (> 0 heating up, < 0 cooling down)
    oil flow   ONAN thermosiphon: flow ∝ Q/ΔT_bottom→top and ΔT ∝ Q^x, so flow ∝ Q^(1−x);
               normalised to its value at FLOW_REF_PU and clipped to 0–1                [est.]
    radiator   k = (Δθo,twin / Δθo,measured)^(1/x): the share of nominal cooling that explains the measured rise;
               only where measured OTI drives ageing (ageing_source == "measured"), 6 h rolling median   [est.]
    V          2^((θh − 98)/6)   (aging_rate / aging_rate_actual, from the engine)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from twin import thermal

FLOW_REF_PU = 1.4          # top of the what-if load range: oil_flow_intensity = 1 there [Assumed]
RADIATOR_MIN_RISE_K = 5.0  # below this rise the ratio is noise: no effectiveness estimate [Assumed]
RADIATOR_WINDOW = "6h"

# column -> (unit, estimated). Estimated = rests on an IEC typical value or a placeholder nameplate value.
COLUMNS: dict[str, tuple[str, bool]] = {
    "bottom_oil_C": ("°C", True),
    "avg_oil_C": ("°C", True),
    "avg_winding_C": ("°C", True),
    "hs_gradient_K": ("K", False),
    "hot_spot_factor": ("", False),
    "top_oil_ss_C": ("°C", False),
    "hot_spot_ss_C": ("°C", False),
    "losses_noload_W": ("W", True),
    "losses_load_W": ("W", True),
    "losses_total_W": ("W", True),
    "heat_dissipated_W": ("W", True),
    "heat_stored_W": ("W", True),
    "oil_flow_intensity": ("", True),
    "radiator_effectiveness": ("", True),
    "tau_oil_min": ("min", False),
    "tau_winding_min": ("min", False),
}


def specs_for(asset: dict):
    """The same library specification the twin engine uses for this asset."""
    return thermal.make_transformer(float(asset["i_rated_A"]), float(asset["load_loss_W"]),
                                    float(asset["no_load_loss_W"])).specs


def params(s, bottom_ratio: float) -> dict:
    """Named model constants (symbols as in IEC 60076-7) for equations and the UI."""
    return {"P0_W": s.no_load_loss, "Pk_W": s.load_loss, "R": s.load_loss / s.no_load_loss,
            "d_theta_or_K": s.top_oil_temp_rise + s.amb_temp_surcharge, "x": s.oil_exp_x, "y": s.winding_exp_y,
            "gr_K": s.winding_oil_gradient, "H": s.hot_spot_fac, "tau_oil_min": s.time_const_oil,
            "tau_winding_min": s.time_const_windings, "I_rated_A": s.nom_load_sec_side, "beta_bottom": bottom_ratio}


def steady(p: dict, K, amb):
    """Steady-state top-oil and hot-spot (°C) at load K (pu) and ambient (°C)."""
    K = np.asarray(K, float)
    top = np.asarray(amb, float) + p["d_theta_or_K"] * ((1 + p["R"] * K ** 2) / (1 + p["R"])) ** p["x"]
    return top, top + p["H"] * p["gr_K"] * K ** p["y"]


def flow_intensity(p: dict, heat_W):
    q_ref = p["P0_W"] + p["Pk_W"] * FLOW_REF_PU ** 2
    return np.clip(np.power(np.clip(np.asarray(heat_W, float), 0, None) / q_ref, 1 - p["x"]), 0, 1)


def compute(trend: pd.DataFrame, asset: dict, bottom_ratio: float) -> pd.DataFrame:
    """Profile columns (COLUMNS) for every row of a run's trend (needs load_pu, amb_C, twin_oil_C, twin_hs_C)."""
    p = params(specs_for(asset), bottom_ratio)
    n = len(trend)
    col = lambda c: trend[c].to_numpy(float) if c in trend else np.full(n, np.nan)
    K, amb, oil, hs = col("load_pu"), col("amb_C"), col("twin_oil_C"), col("twin_hs_C")
    out = pd.DataFrame(index=trend.index)
    out["bottom_oil_C"] = amb + bottom_ratio * (oil - amb)
    out["avg_oil_C"] = (oil + out["bottom_oil_C"]) / 2
    out["avg_winding_C"] = out["avg_oil_C"] + p["gr_K"] * K ** p["y"]
    out["hs_gradient_K"] = hs - oil
    out["hot_spot_factor"] = np.where(np.isnan(K), np.nan, p["H"])
    out["top_oil_ss_C"], out["hot_spot_ss_C"] = steady(p, K, amb)
    out["losses_noload_W"] = np.where(np.isnan(K), np.nan, p["P0_W"])
    out["losses_load_W"] = p["Pk_W"] * K ** 2
    out["losses_total_W"] = out["losses_noload_W"] + out["losses_load_W"]
    rise = np.clip(oil - amb, 0, None)
    out["heat_dissipated_W"] = (p["P0_W"] + p["Pk_W"]) * (rise / p["d_theta_or_K"]) ** (1 / p["x"])
    out["heat_stored_W"] = out["losses_total_W"] - out["heat_dissipated_W"]
    out["oil_flow_intensity"] = flow_intensity(p, out["heat_dissipated_W"])
    out["radiator_effectiveness"] = _radiator(trend, rise, p)
    out["tau_oil_min"] = np.where(np.isnan(K), np.nan, p["tau_oil_min"])
    out["tau_winding_min"] = np.where(np.isnan(K), np.nan, p["tau_winding_min"])
    return out


def _radiator(trend: pd.DataFrame, twin_rise: np.ndarray, p: dict) -> np.ndarray:
    n = len(trend)
    if "OTI_C" not in trend or "ageing_source" not in trend or "timestamp" not in trend:
        return np.full(n, np.nan)
    meas_rise = trend["OTI_C"].to_numpy(float) - trend["amb_C"].to_numpy(float)
    use = (trend["ageing_source"].to_numpy() == "measured") & (twin_rise >= RADIATOR_MIN_RISE_K) & (meas_rise > 0)
    k = np.full(n, np.nan)
    k[use] = (twin_rise[use] / meas_rise[use]) ** (1 / p["x"])
    s = pd.Series(k, index=pd.DatetimeIndex(trend["timestamp"]))
    return np.clip(s.rolling(RADIATOR_WINDOW, min_periods=1).median().to_numpy(), 0, 1.5)


def whatif(p: dict, K: float, amb: float, cooling: float, start_top: float | None = None,
           start_grad: float | None = None, settle_K: float = 1.0, points: int = 61) -> dict:
    """Steady state at load K (pu), ambient (°C) and cooling effectiveness (1 = radiators as designed).

    Reduced cooling scales the top-oil rise by cooling^(−x) (inverse of A30's k); the winding gradient does not
    depend on the radiators. The approach from a start state uses the IEC 60076-7 exponential equations with the
    library's k11 = k21 = 1: θo(t) = θo,ss + (θo,0 − θo,ss)·e^(−t/τo), gradient likewise with τw.
    time_to_steady_min: until both are within settle_K of steady state (3·τo from cold when no start is given).
    """
    from twin import ageing
    k = min(1.5, max(0.05, float(cooling)))
    rise_nom = p["d_theta_or_K"] * ((1 + p["R"] * K ** 2) / (1 + p["R"])) ** p["x"]
    rise = rise_nom * k ** (-p["x"])
    grad = p["H"] * p["gr_K"] * K ** p["y"]
    top, hs = amb + rise, amb + rise + grad
    hs_nom = amb + rise_nom + grad
    v, v_nom = (float(x) for x in ageing.rate([hs, hs_nom]))
    losses = p["P0_W"] + p["Pk_W"] * K ** 2
    bottom = amb + p["beta_bottom"] * rise
    avg_w = (top + bottom) / 2 + p["gr_K"] * K ** p["y"]
    t0, g0 = (amb, 0.0) if start_top is None else (float(start_top), float(start_grad or 0.0))
    to, tw = p["tau_oil_min"], p["tau_winding_min"]
    need_o = to * np.log(abs(t0 - top) / settle_K) if abs(t0 - top) > settle_K else 0.0
    need_w = tw * np.log(abs(g0 - grad) / settle_K) if abs(g0 - grad) > settle_K else 0.0
    t_settle = max(need_o, need_w)
    tt = np.linspace(0, max(4 * to, t_settle * 1.1), points)
    top_t = top + (t0 - top) * np.exp(-tt / to)
    hs_t = top_t + grad + (g0 - grad) * np.exp(-tt / tw)
    return {
        "load_pu": K, "ambient_C": amb, "cooling": k, "current_A": K * p["I_rated_A"],
        "top_oil_C": top, "hot_spot_C": hs, "bottom_oil_C": bottom, "avg_winding_C": avg_w,
        "winding_gradient_K": grad, "hot_spot_factor": p["H"],
        "losses_noload_W": p["P0_W"], "losses_load_W": p["Pk_W"] * K ** 2, "losses_total_W": losses,
        "heat_dissipated_W": losses, "heat_stored_W": 0.0,
        "oil_flow_intensity": float(flow_intensity(p, losses)), "radiator_effectiveness": k,
        "tau_oil_min": to, "tau_winding_min": tw,
        "ageing_rate": v, "ageing_rate_nominal_cooling": v_nom, "hot_spot_nominal_cooling_C": hs_nom,
        "time_to_steady_min": float(t_settle),
        "curve": {"t_min": tt.tolist(), "top_oil_C": top_t.tolist(), "hot_spot_C": hs_t.tolist()},
        "start": {"top_oil_C": t0, "gradient_K": g0, "from": "cold (ambient)" if start_top is None else "twin state"},
    }
