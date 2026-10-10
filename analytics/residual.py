"""Residual detector: measured oil temperature drifting from the twin. OWNER: Agent A (load-robust rev: Agent D).

Contract:
    calibrate(normal_df, thresholds) -> dict           # mean, sigma, trip level from the Normal scenario
    detect(df, thresholds, reference=None) -> list[Alert]
Reads: residual_oil_C, twin_oil_C, amb_C. Emits alert type: residual_drift (detector="residual").
Threshold = reference mean + sigma_mult * sigma, persistent for persist_h (thresholds.operating.residual).

The test statistic is the residual NORMALISED by the twin's rise above ambient:
    rel = residual_oil_C / (twin_oil_C - amb_C)
because twin-vs-plant mismatch grows with load; an absolute trip calibrated at Normal load fires on overload
(S1) although nothing is wrong with the cooling. A cooling fault scales the rise, so rel still shows it.
Fallback to the absolute residual (previous behaviour) when twin_oil_C/amb_C are missing, or when the reference
was produced by the old calibrate() (no rel_* keys). Re-calibrate to get the load-robust behaviour.
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
# DECISION (not in thresholds.yaml): samples whose twin rise above ambient is below this are masked out of the
# normalised test (the ratio is noise-dominated when there is almost no rise).
MIN_RISE_C = 10.0


def _residual(df: pd.DataFrame) -> pd.Series | None:
    if "residual_oil_C" not in df.columns:
        return None
    r = pd.to_numeric(df["residual_oil_C"], errors="coerce")
    return None if r.isna().all() else r


def _rel(df: pd.DataFrame) -> pd.Series | None:
    """residual / twin rise above ambient; NaN where rise < MIN_RISE_C. None if inputs are missing."""
    r = _residual(df)
    if r is None or "twin_oil_C" not in df.columns or "amb_C" not in df.columns:
        return None
    rise = pd.to_numeric(df["twin_oil_C"], errors="coerce") - pd.to_numeric(df["amb_C"], errors="coerce")
    rel = r / rise.where(rise >= MIN_RISE_C)
    return None if rel.notna().sum() < 2 else rel


def calibrate(normal_df: pd.DataFrame, thresholds: dict) -> dict:
    """Mean, sigma and trip of the Normal residual (absolute and load-normalised). Empty dict if no residual."""
    nd = strip_quarantined(normal_df)
    r = _residual(nd)
    if r is None:
        return {}
    cfg = thresholds["operating"]["residual"]
    k = cfg["sigma_mult"]
    vals = r.dropna()
    mean = float(vals.mean())
    sigma = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
    ref = {"mean": mean, "sigma": sigma, "sigma_mult": k, "trip": mean + k * sigma, "n": int(len(vals))}
    rel = _rel(nd)
    if rel is not None:
        rv = rel.dropna()
        rm, rs = float(rv.mean()), float(rv.std(ddof=1))
        ref.update({"rel_mean": rm, "rel_sigma": rs, "rel_trip": rm + k * rs, "rel_n": int(len(rv)),
                    "min_rise_C": MIN_RISE_C})
    return ref


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
    rel = _rel(df) if "rel_trip" in reference else None
    relative = rel is not None
    if relative:
        series, trip, mean, sigma = rel, reference["rel_trip"], reference["rel_mean"], reference["rel_sigma"]
    elif "trip" in reference:  # old-style reference, or twin/ambient columns missing: absolute residual
        series, trip, mean, sigma = r, reference["trip"], reference["mean"], reference["sigma"]
    else:
        return []
    steps = max(1, int(round(cfg["persist_h"] / step_hours(df))))
    rolled = series.rolling(steps, min_periods=steps).mean()
    mask = persistent_mask((rolled > trip).to_numpy(), steps)
    gap = int(round(MERGE_GAP_H / step_hours(df)))
    found = runs(mask)
    for (_, prev_end), (next_start, _) in zip(found, found[1:]):
        if next_start - prev_end - 1 < gap:
            mask[prev_end + 1 : next_start] = True
    basis = "self-referenced baseline (first 7 days of this data)" if self_ref else "Normal-scenario baseline"
    sm = reference["sigma_mult"]
    out = []
    for start, _ in runs(mask):
        v = float(rolled.iloc[start])
        sim = bool(df["simulated"].iloc[start]) if "simulated" in df.columns else True
        if relative:
            meas = (
                f"Measured top-oil temperature exceeds the twin by {100 * v:.1f} % of the twin's rise above ambient "
                f"on a {cfg['persist_h']} h average, above the {100 * trip:.1f} % trip (baseline mean "
                f"{100 * mean:.1f} % + {sm} sigma of {100 * sigma:.2f} %; load-normalised; {basis})."
            )
        else:
            meas = (
                f"Measured top-oil temperature is {v:.1f} C above the twin on a {cfg['persist_h']} h "
                f"average, above the {trip:.1f} C trip (baseline mean {mean:.1f} C + "
                f"{sm} sigma of {sigma:.2f} C; {basis})."
            )
        out.append(
            make_alert(
                df["timestamp"].iloc[start], "residual_drift", "warning", "residual",
                value=v, threshold=trip,
                explanation=meas + " Possible cooling degradation.",
                simulated=sim,
            )
        )
    return out
