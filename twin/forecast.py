"""Looking ahead with the same physics: headroom, time to a limit, a 24 h forecast, remaining-life distribution.

    headroom(asset, ambient_C)                      largest steady load that keeps the hot spot and top oil in limits
    time_to_limit(asset, load_pu, ambient_C, oil)   hours until a limit is reached at the present load
    forecast_24h(trend, asset, t)                   next 24 h from seasonal-naive load and weather, through the model
    rul_distribution(asset, trend, ...)             Monte Carlo remaining insulation life, P10 / P50 / P90 and a fan
    trip_risk_30d(asset, trend, ...)                chance a limit is reached within 30 days

Remaining life here is insulation life under the IEC 60076-7 ageing rate if present conditions persist. It is a model
outcome, not a field-validated failure forecast. Every random draw is seeded, so a run is reproducible.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.signal import lfilter

from twin import ageing, profile, thermal

HOT_SPOT_LIMIT_C = 120.0     # thresholds.yaml hot_spot_c.critical [Assumed]
TOP_OIL_LIMIT_C = 95.0       # thresholds.yaml top_oil_c.critical [Assumed]
HORIZON_YEARS = 60
FAN_YEARS = 40


def _specs(asset: dict):
    a = profile.complete(asset)
    tr = thermal.make_transformer(float(a["i_rated_A"]), float(a["load_loss_W"]), float(a["no_load_loss_W"]),
                                  **profile.thermal_kwargs(a))
    return a, tr.specs


def _ult_rise(s, K):
    """Steady top-oil rise over ambient at load K (per unit), IEC 60076-7 with the library's enclosure allowance."""
    R = s.load_loss / s.no_load_loss
    return (s.top_oil_temp_rise + s.amb_temp_surcharge) * ((1 + R * np.asarray(K) ** 2) / (1 + R)) ** s.oil_exp_x


def _gradient(s, K):
    return s.hot_spot_fac * s.winding_oil_gradient * np.asarray(K) ** s.winding_exp_y


def headroom(asset: dict, ambient_C: float, hs_limit: float = HOT_SPOT_LIMIT_C, oil_limit: float = TOP_OIL_LIMIT_C) -> dict:
    """Largest steady load (per unit) at this ambient with hot spot <= hs_limit and top oil <= oil_limit (bisection)."""
    _, s = _specs(asset)

    def ok(K):
        oil = ambient_C + _ult_rise(s, K)
        return oil <= oil_limit and oil + _gradient(s, K) <= hs_limit

    if not ok(0.0):
        return {"pu": 0.0, "limiting": "ambient too high", "ambient_C": round(float(ambient_C), 1)}
    lo, hi = 0.0, 3.0
    if ok(hi):
        return {"pu": hi, "limiting": None, "ambient_C": round(float(ambient_C), 1)}
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    K = lo
    oil = ambient_C + _ult_rise(s, K)
    return {"pu": round(float(K), 3), "ambient_C": round(float(ambient_C), 1),
            "limiting": "top oil" if abs(oil - oil_limit) < abs(oil + _gradient(s, K) - hs_limit) else "hot spot"}


def time_to_limit(asset: dict, load_pu: float, ambient_C: float, oil_now_C: float,
                  hs_limit: float = HOT_SPOT_LIMIT_C, oil_limit: float = TOP_OIL_LIMIT_C) -> dict:
    """Hours until the top oil (or the hot spot, through the oil) reaches its limit if the load stays as it is now.

    t = -tau * ln((target - ultimate) / (now - ultimate)), exact for a first-order lag at a constant load.
    """
    _, s = _specs(asset)
    K = float(load_pu)
    ult = ambient_C + float(_ult_rise(s, K))
    target = min(oil_limit, hs_limit - float(_gradient(s, K)))
    if oil_now_C >= target:
        return {"status": "already_reached", "hours": 0.0}
    if ult <= target:
        return {"status": "not_reached", "hours": None, "steady_state_oil_C": round(ult, 1), "target_oil_C": round(target, 1)}
    hours = -(s.time_const_oil / 60.0) * np.log((target - ult) / (oil_now_C - ult))
    return {"status": "reaches_limit", "hours": round(float(hours), 1), "steady_state_oil_C": round(ult, 1), "target_oil_C": round(target, 1)}


# ---------------------------------------------------------------- 24 h forecast
def _in_zone(t, trend: pd.DataFrame) -> pd.Timestamp:
    """t expressed in the data's own time zone, so hour-of-day profiles line up with local time."""
    t = pd.Timestamp(t)
    tz = trend["timestamp"].dt.tz if "timestamp" in trend else None
    if tz is None:
        return t.tz_localize(None) if t.tzinfo is not None else t
    return t.tz_localize(tz) if t.tzinfo is None else t.tz_convert(tz)


def _hourly_profile(trend: pd.DataFrame, col: str, end: pd.Timestamp, days: int = 7) -> np.ndarray:
    """Mean of `col` for each hour of the day over the last `days` days before `end` (NaN where there is no data)."""
    w = trend[(trend["timestamp"] <= end) & (trend["timestamp"] > end - pd.Timedelta(days=days))]
    out = np.full(24, np.nan)
    if w.empty:
        return out
    g = w.groupby(w["timestamp"].dt.hour)[col].mean()
    out[g.index.to_numpy()] = g.to_numpy()
    return out


def _fill(profile_24: np.ndarray, fallback: float) -> np.ndarray:
    p = profile_24.copy()
    ok = ~np.isnan(p)
    if not ok.any():
        return np.full(24, fallback)
    idx = np.arange(24)
    return np.interp(idx, np.r_[idx[ok] - 24, idx[ok], idx[ok] + 24], np.r_[p[ok], p[ok], p[ok]])


def forecast_24h(trend: pd.DataFrame, asset: dict, t: pd.Timestamp) -> dict:
    """Next 24 h of top oil and hot spot. Load and ambient are the hour-of-day means of the last 7 days (seasonal
    naive), run through the thermal model after a 24 h run-in on the real data. The band comes from the twin's own
    recent errors against the measured oil temperature, or a stated default when there is no oil sensor."""
    need = {"timestamp", "I_mean", "amb_C"}
    if not need <= set(trend.columns):
        return {"available": False, "reason": "needs a load and ambient-temperature time series"}
    a, tr = profile.complete(asset), None
    tr = thermal.make_transformer(float(a["i_rated_A"]), float(a["load_loss_W"]), float(a["no_load_loss_W"]), **profile.thermal_kwargs(a))
    t = _in_zone(t, trend)
    hist = trend[trend["timestamp"] <= t].dropna(subset=["I_mean", "amb_C"])
    if len(hist) < 8:
        return {"available": False, "reason": "not enough history before this time"}
    step = hist["timestamp"].diff().median()
    if not isinstance(step, pd.Timedelta) or step <= pd.Timedelta(0) or step > pd.Timedelta(hours=2):
        return {"available": False, "reason": "the sampling interval is too coarse to forecast"}
    past = hist[hist["timestamp"] > t - pd.Timedelta(hours=24)]
    n_future = int(round(pd.Timedelta(hours=24) / step))
    future_ts = pd.DatetimeIndex([t + step * (i + 1) for i in range(n_future)])
    i_rated = float(a["i_rated_A"])
    load_prof = _fill(_hourly_profile(hist.assign(K=hist["I_mean"] / i_rated), "K", t), float(hist["I_mean"].iloc[-1]) / i_rated)
    amb_prof = _fill(_hourly_profile(hist, "amb_C", t), float(hist["amb_C"].iloc[-1]))
    f_amps = load_prof[future_ts.hour.to_numpy()] * i_rated
    f_amb = amb_prof[future_ts.hour.to_numpy()]
    ts_all = pd.Series(list(past["timestamp"]) + list(future_ts))
    amps = np.r_[past["I_mean"].to_numpy(float), f_amps]
    amb = np.r_[past["amb_C"].to_numpy(float), f_amb]
    oil, hs = thermal.run_segment(tr, ts_all, amps, amb)
    k = len(past)
    oil_f, hs_f = oil[k:], hs[k:]

    lo = hi = 2.0
    basis = "assumed ±2 K (no measured oil temperature to judge the twin's error)"
    if "OTI_C" in trend.columns and "twin_oil_C" in trend.columns:
        r = (hist["OTI_C"] - hist["twin_oil_C"]).dropna().tail(int(round(pd.Timedelta(days=7) / step)))
        if len(r) >= 24:
            lo, hi = float(-np.quantile(r - r.median(), 0.10)), float(np.quantile(r - r.median(), 0.90))
            basis = "the twin's own errors against the measured oil temperature over the last 7 days (10th to 90th percentile)"
    r2 = lambda x: [round(float(v), 1) for v in x]  # noqa: E731
    return {"available": True, "t": [x.isoformat() for x in future_ts], "top_oil_C": r2(oil_f), "hot_spot_C": r2(hs_f),
            "band_low_K": round(lo, 2), "band_high_K": round(hi, 2), "band_basis": basis,
            "top_oil_lo": r2(oil_f - lo), "top_oil_hi": r2(oil_f + hi), "hot_spot_lo": r2(hs_f - lo), "hot_spot_hi": r2(hs_f + hi),
            "peak_hot_spot_C": round(float(np.nanmax(hs_f)), 1), "peak_top_oil_C": round(float(np.nanmax(oil_f)), 1),
            "method": "Seasonal-naive load and ambient (same hour, last 7 days) through the IEC 60076-7 model."}


# ---------------------------------------------------------------- Monte Carlo
def _day_profile(trend: pd.DataFrame, asset: dict, end: pd.Timestamp) -> tuple[np.ndarray, np.ndarray]:
    i_rated = float(profile.complete(asset)["i_rated_A"])
    h = trend.dropna(subset=["I_mean", "amb_C"])
    h = h[h["timestamp"] <= end]
    if h.empty:
        raise ValueError("no load and ambient history to base a projection on")
    k = _fill(_hourly_profile(h.assign(K=h["I_mean"] / i_rated), "K", end), float((h["I_mean"] / i_rated).mean()))
    amb = _fill(_hourly_profile(h, "amb_C", end), float(h["amb_C"].mean()))
    return k, amb


def _hourly_rate(s, K, amb, phi, insulation: str = "normal"):
    """Ageing rate per hour for 24 h profiles K, amb (runs x 24): lagged top oil + winding gradient. Vectorised."""
    ult = amb + phi[:, None] * _ult_rise(s, K)
    a = 1.0 - np.exp(-1.0 / (s.time_const_oil / 60.0))
    rep = np.tile(ult, (1, 4))                                    # let the cycle settle, keep the last day
    oil = lfilter([a], [1.0, -(1.0 - a)], rep, axis=1, zi=(1.0 - a) * rep[:, :1] * np.ones((1, 1)))[0][:, -24:]
    hs = oil + _gradient(s, K)
    ref = 98.0 if insulation == "normal" else 110.0
    return 2.0 ** np.clip((hs - ref) / 6.0, -60.0, 40.0)


def rul_distribution(asset: dict, trend: pd.DataFrame, t: pd.Timestamp, consumed_h: float, reference_life_h: float,
                     risk_years: dict, n: int = 500, seed: int = 0) -> dict:
    """Monte Carlo remaining insulation life. Draws: load level, ambient shift, load growth (2 %/yr ± 1.5), cooling
    degradation from the twin's recent residual, ±30 % ageing-model uncertainty, ±5 % initial-life uncertainty."""
    a, s = _specs(asset)
    rng = np.random.default_rng(seed)
    t = _in_zone(t, trend)
    k24, amb24 = _day_profile(trend, a, t)

    phi0 = 1.0
    if {"residual_oil_C", "twin_oil_C", "amb_C", "timestamp"} <= set(trend.columns):
        w = trend[(trend["timestamp"] <= t) & (trend["timestamp"] > pd.Timestamp(t) - pd.Timedelta(days=7))]
        rise = (w["twin_oil_C"] - w["amb_C"]).where(lambda x: x > 8)
        rel = (w["residual_oil_C"] / rise).dropna()
        if len(rel) >= 24:
            phi0 = float(np.clip(1.0 + max(rel.median(), 0.0), 1.0, 1.6))

    scale = rng.lognormal(0.0, 0.08, n)
    shift = rng.normal(0.0, 2.0, n)
    growth = rng.normal(0.02, 0.015, n)
    phi = phi0 * rng.normal(1.0, 0.03, n)
    unc = rng.lognormal(0.0, 0.25, n)
    init = np.clip(consumed_h + rng.normal(0.0, 0.05 * reference_life_h, n), 0.0, None)
    ins = a.get("insulation", "normal")

    yearly = np.empty((n, HORIZON_YEARS + 1))
    for y in range(HORIZON_YEARS + 1):
        K = k24[None, :] * scale[:, None] * ((1.0 + growth) ** y)[:, None]
        rate = _hourly_rate(s, K, amb24[None, :] + shift[:, None], phi, ins).mean(axis=1)
        yearly[:, y] = rate * unc * 8766.0                        # equivalent hours of life used in year y
    cum = np.cumsum(yearly, axis=1)
    used = init[:, None] + cum                                    # life used by the END of year y
    remaining = np.clip(reference_life_h - init, 0.0, None)
    reached = used >= reference_life_h
    first = np.where(reached.any(axis=1), reached.argmax(axis=1), HORIZON_YEARS + 1)
    prev = np.where(first > 0, np.take_along_axis(used, np.clip(first - 1, 0, HORIZON_YEARS)[:, None], axis=1)[:, 0], init)
    cur = np.take_along_axis(used, np.clip(first, 0, HORIZON_YEARS)[:, None], axis=1)[:, 0]
    frac = np.where(cur > prev, (reference_life_h - prev) / np.maximum(cur - prev, 1e-9), 0.0)
    years = np.where(first <= HORIZON_YEARS, np.clip(first + frac, 0, HORIZON_YEARS), float(HORIZON_YEARS))
    years = np.where(remaining <= 0, 0.0, years)
    p10, p50, p90 = (float(np.quantile(years, q)) for q in (0.10, 0.50, 0.90))
    fan_x = list(range(FAN_YEARS + 1))
    pct = np.clip(np.hstack([init[:, None], used[:, :FAN_YEARS]]) / reference_life_h * 100.0, 0.0, 100.0)
    q = lambda p: [round(float(v), 2) for v in np.quantile(pct, p, axis=0)]  # noqa: E731
    risk = "High" if p10 < risk_years["high"] else "Med" if p10 < risk_years["medium"] else "Low"
    return {"years_p10": round(p10, 1), "years_p50": round(p50, 1), "years_p90": round(p90, 1), "risk": risk,
            "censored_fraction": round(float((first > HORIZON_YEARS).mean()), 3), "horizon_years": HORIZON_YEARS,
            "fan": {"years": fan_x, "p10": q(0.10), "p50": q(0.50), "p90": q(0.90)},
            "inputs": {"consumed_life_pct": round(consumed_h / reference_life_h * 100, 2), "cooling_factor": round(phi0, 3),
                       "runs": n, "reference_life_h": reference_life_h},
            "note": "Insulation life under the IEC 60076-7 ageing model if present conditions persist. A distribution, not a date, "
                    "and not a field-validated failure forecast."}


def trip_risk_30d(asset: dict, trend: pd.DataFrame, t: pd.Timestamp, n: int = 400, seed: int = 0,
                  hs_limit: float = HOT_SPOT_LIMIT_C, oil_limit: float = TOP_OIL_LIMIT_C) -> dict:
    """Chance, over 30 simulated days of the recent load pattern with day-to-day variation, that the top oil or hot spot
    reaches its limit."""
    a, s = _specs(asset)
    rng = np.random.default_rng(seed + 1)
    t = _in_zone(t, trend)
    k24, amb24 = _day_profile(trend, a, t)
    days = 30
    day_scale = rng.lognormal(0.0, 0.07, (n, days))
    day_shift = rng.normal(0.0, 1.5, (n, days))
    K = (k24[None, None, :] * day_scale[:, :, None]).reshape(n, days * 24)
    amb = (amb24[None, None, :] + day_shift[:, :, None]).reshape(n, days * 24)
    ult = amb + _ult_rise(s, K)
    al = 1.0 - np.exp(-1.0 / (s.time_const_oil / 60.0))
    oil = lfilter([al], [1.0, -(1.0 - al)], ult, axis=1, zi=(1.0 - al) * ult[:, :1])[0]
    hs = oil + _gradient(s, K)
    hit = (oil.max(axis=1) >= oil_limit) | (hs.max(axis=1) >= hs_limit)
    return {"probability": round(float(hit.mean()), 3), "days": days, "runs": n,
            "limits": {"top_oil_C": oil_limit, "hot_spot_C": hs_limit},
            "median_peak_hot_spot_C": round(float(np.median(hs.max(axis=1))), 1)}
