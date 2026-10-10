"""Remaining useful life from thermal ageing (FINAL_PRD.md §8.9). A range, never a date.

consumed = assumed service years (at ageing rate 1) + ACTUAL equivalent days aged in the data
RUL      = (reference life − consumed) / recent ageing rate, recent = last 7 days
range    = remaining / highest daily rate  …  remaining / lowest daily rate in that window
Thermal ageing only: no moisture, PD or DGA. Under normal load the rate is ≪ 1, so RUL is long — that is correct.
"""
import numpy as np
import pandas as pd

from contracts.models import RUL


def estimate(twin: pd.DataFrame, years_in_service: float, cfg: dict) -> RUL | None:
    t = (twin[["timestamp", "aging_rate_actual", "dt_min"]].dropna(subset=["aging_rate_actual"])
         .rename(columns={"aging_rate_actual": "aging_rate"}))
    if t.empty:
        return None
    ref_days = cfg["reference_life_h"] / 24
    consumed = years_in_service * 365.25 + float(twin["days_aged_actual_cum"].dropna().iloc[-1])
    remaining = max(ref_days - consumed, 0.0)
    end = t["timestamp"].iloc[-1]
    w = t[t["timestamp"] > end - pd.Timedelta(days=cfg["rul_window_days"])]
    dt = w["dt_min"].to_numpy()
    recent = float((w["aging_rate"] * dt).sum() / dt.sum()) if dt.sum() > 0 else float(w["aging_rate"].mean())
    daily = (w.assign(a=w["aging_rate"] * w["dt_min"]).set_index("timestamp")
             .resample("1D")[["a", "dt_min"]].sum())
    daily = daily[daily["dt_min"] > 0]
    d = (daily["a"] / daily["dt_min"]).to_numpy() if len(daily) else np.array([recent])
    cap = cfg["rul_cap_years"]

    def years(rate):
        return cap if rate <= 0 else min(remaining / rate / 365.25, cap)

    lo, hi = years(float(d.max())), years(float(d.min()))
    risk = "High" if lo < cfg["risk_years"]["high"] else "Med" if lo < cfg["risk_years"]["medium"] else "Low"
    return RUL(years_low=round(lo, 2), years_high=round(hi, 2), risk=risk,
               consumed_days=round(consumed, 2), recent_rate=round(recent, 4))


def display(r: RUL | None, cfg: dict) -> str:
    """Dashboard text. Primary figures are life consumed and ageing rate; RUL is capped for display only."""
    if r is None:
        return "RUL: not available"
    cap = cfg["rul_display_cap_years"]
    f = lambda y: f"> {cap:g}" if y >= cap else f"{y:.1f}"  # noqa: E731
    lo, hi = f(r.years_low), f(r.years_high)
    return f"RUL {lo} years" if lo == hi else f"RUL {lo} – {hi} years"
