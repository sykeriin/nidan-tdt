"""Residual detector: measured oil temperature drifting from the twin. OWNER: Agent A.

Contract:
    calibrate(normal_df, thresholds) -> dict           # mean, sigma, trip level from the Normal scenario
    detect(df, thresholds, reference=None) -> list[Alert]
Reads: residual_oil_C. Emits alert type: residual_drift (detector="residual").
Threshold = reference mean + sigma_mult * sigma, persistent for persist_h (thresholds.operating.residual).
If residual_oil_C is all NaN (meter-only mode) return [].
Without a reference the baseline is the first BASELINE_DAYS of df itself (self-referenced).
"""
from __future__ import annotations

import pandas as pd

from analytics.common import make_alert, persistent_mask, runs, step_hours, strip_quarantined
from contracts.models import Alert

BASELINE_DAYS = 7  # self-referenced baseline length when no Normal reference is supplied
# Not in thresholds.yaml. The residual follows the daily load cycle, so a drift dips under the trip at night.
# Excursions separated by less than this are one episode (one alert).
MERGE_GAP_H = 24.0


def _residual(df: pd.DataFrame) -> pd.Series | None:
    if "residual_oil_C" not in df.columns:
        return None
    r = pd.to_numeric(df["residual_oil_C"], errors="coerce")
    return None if r.isna().all() else r


def calibrate(normal_df: pd.DataFrame, thresholds: dict) -> dict:
    """Mean, sigma and trip level of the Normal residual. Empty dict if there is no residual."""
    r = _residual(strip_quarantined(normal_df))
    if r is None:
        return {}
    cfg = thresholds["operating"]["residual"]
    vals = r.dropna()
    mean = float(vals.mean())
    sigma = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
    return {
        "mean": mean, "sigma": sigma, "sigma_mult": cfg["sigma_mult"],
        "trip": mean + cfg["sigma_mult"] * sigma, "n": int(len(vals)),
    }


def detect(df: pd.DataFrame, thresholds: dict, reference: dict | None = None) -> list[Alert]:
    df = strip_quarantined(df).reset_index(drop=True)
    r = _residual(df)
    if r is None or len(df) < 2 or "timestamp" not in df.columns:  # sampling interval undefined below 2 rows
        return []
    cfg = thresholds["operating"]["residual"]
    self_ref = not reference
    if self_ref:
        ts = pd.to_datetime(df["timestamp"])
        reference = calibrate(df[ts < ts.iloc[0] + pd.Timedelta(days=BASELINE_DAYS)], thresholds)
        if not reference:
            return []
    trip = reference["trip"]
    steps = max(1, int(round(cfg["persist_h"] / step_hours(df))))
    rolled = r.rolling(steps, min_periods=steps).mean()
    mask = persistent_mask((rolled > trip).to_numpy(), steps)
    gap = int(round(MERGE_GAP_H / step_hours(df)))
    found = runs(mask)
    for (_, prev_end), (next_start, _) in zip(found, found[1:]):
        if next_start - prev_end - 1 < gap:
            mask[prev_end + 1 : next_start] = True
    basis = "self-referenced baseline (first 7 days of this data)" if self_ref else "Normal-scenario baseline"
    out = []
    for start, _ in runs(mask):
        v = float(rolled.iloc[start])
        sim = bool(df["simulated"].iloc[start]) if "simulated" in df.columns else True
        out.append(
            make_alert(
                df["timestamp"].iloc[start], "residual_drift", "warning", "residual",
                value=v, threshold=trip,
                explanation=(
                    f"Measured top-oil temperature is {v:.1f} C above the twin on a {cfg['persist_h']} h "
                    f"average, above the {trip:.1f} C trip (baseline mean {reference['mean']:.1f} C + "
                    f"{reference['sigma_mult']} sigma of {reference['sigma']:.2f} C; {basis}). "
                    "Possible cooling degradation."
                ),
                simulated=sim,
            )
        )
    return out
