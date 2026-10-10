"""Lead time vs a plain-threshold baseline. OWNER: Agent C (proof).

Contract:
    baseline_crossings(df, thresholds, since=None) -> dict[str, pd.Timestamp | None]
        first time each plain absolute threshold is crossed (the "dumb" baseline, no twin)
    lead_times(alerts, ground_truth, df, thresholds) -> pd.DataFrame
        one row per ground-truth fault: fault, gt_onset, detected, first_alert_ts, first_alert_type,
        baseline_rule, baseline_ts, lead_vs_baseline_h, lead_vs_onset_h (negative = detected after onset), detector

Baseline rules (thresholds.yaml, no twin, absolute values only):
    loading_alarm        loading_pct / 100 >= loading_pu.alarm
    overcurrent          I_mean / reference.i_rated_a >= overcurrent_pu.alarm
    top_oil_warning      OTI_C >= top_oil_c.warning
    hot_spot_warning     WTI_C >= hot_spot_c.warning
    unbalance_warning    max|Iphase - I_mean| / I_mean * 100 >= current_unbalance_pct.warning
    oil_level_low        OLI_pct <= oil_level_pct.low

Baseline per fault:
    overload             earliest of loading_alarm, overcurrent
    cooling_degradation  top_oil_warning
    unbalance            unbalance_warning
    oil_leak             oil_level_low
    oil_theft            oil_level_low, counting only samples at or after the onset. If the level is already
                         low (for example after a leak) the rule fires at the first sample, so lead is ~0 or negative
    through_fault        none: a trend-only baseline cannot see events that are invisible in 15-minute data

If the baseline never fires, baseline_ts is None and lead_vs_baseline_h is NaN. That is a real result (the plain
threshold NEVER alarms), not a missing value. Ground truth is used only here, never by detectors.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics.common import strip_quarantined
from contracts.models import Alert

FAULT_BASELINE: dict[str, tuple[str, ...]] = {
    "overload": ("loading_alarm", "overcurrent"),
    "cooling_degradation": ("top_oil_warning",),
    "unbalance": ("unbalance_warning",),
    "oil_leak": ("oil_level_low",),
    "oil_theft": ("oil_level_low",),
    "through_fault": (),
}
MATCH_GRACE_H = 24.0  # an alert still matches a fault this long after the fault window ends
COLUMNS = [
    "fault", "gt_onset", "detected", "first_alert_ts", "first_alert_type", "baseline_rule",
    "baseline_ts", "lead_vs_baseline_h", "lead_vs_onset_h", "detector",
]


def _current_unbalance_pct(df: pd.DataFrame) -> pd.Series:
    mean = df["I_mean"].astype(float)
    dev = df[["IR", "IY", "IB"]].astype(float).sub(mean, axis=0).abs().max(axis=1)
    return dev / mean.replace(0.0, np.nan) * 100.0


def baseline_crossings(df: pd.DataFrame, thresholds: dict, since: pd.Timestamp | None = None) -> dict:
    """First crossing time per plain-threshold rule, or None. `since` ignores earlier samples."""
    d = strip_quarantined(df)
    ts = pd.to_datetime(d["timestamp"])
    op = thresholds["operating"]
    i_rated = float(thresholds["reference"]["i_rated_a"])
    masks = {
        "loading_alarm": d["loading_pct"] / 100.0 >= op["loading_pu"]["alarm"],
        "overcurrent": d["I_mean"] / i_rated >= op["overcurrent_pu"]["alarm"],
        "top_oil_warning": d["OTI_C"] >= op["top_oil_c"]["warning"],
        "hot_spot_warning": d["WTI_C"] >= op["hot_spot_c"]["warning"],
        "unbalance_warning": _current_unbalance_pct(d) >= op["current_unbalance_pct"]["warning"],
        "oil_level_low": d["OLI_pct"] <= op["oil_level_pct"]["low"],
    }
    if since is not None:
        after = ts >= pd.Timestamp(since)
        masks = {k: m & after for k, m in masks.items()}
    out: dict = {}
    for name, m in masks.items():
        hit = ts[m.to_numpy(dtype=bool)]
        out[name] = hit.iloc[0] if len(hit) else None
    return out


def alert_matches_fault(alert: Alert, fault: dict) -> bool:
    """True if the alert type is expected for the fault and falls in [onset, end + 24 h]."""
    if alert.type not in fault["expect"]:
        return False
    t = pd.Timestamp(alert.timestamp)
    return pd.Timestamp(fault["onset"]) <= t <= pd.Timestamp(fault["end"]) + pd.Timedelta(hours=MATCH_GRACE_H)


def _hours(delta: pd.Timedelta) -> float:
    return float(delta / pd.Timedelta(hours=1))


def lead_times(alerts: list[Alert], ground_truth: list[dict], df: pd.DataFrame, thresholds: dict) -> pd.DataFrame:
    """One row per ground-truth fault comparing the first matching alert with the plain-threshold baseline."""
    rows = []
    for fault in ground_truth:
        onset = pd.Timestamp(fault["onset"])
        matched = sorted((a for a in alerts if alert_matches_fault(a, fault)), key=lambda a: pd.Timestamp(a.timestamp))
        first = matched[0] if matched else None
        rules = FAULT_BASELINE.get(fault["fault"], ())
        crossings = baseline_crossings(df, thresholds, since=onset if fault["fault"] == "oil_theft" else None)
        hits = [(crossings[r], r) for r in rules if crossings.get(r) is not None]
        base_ts, base_rule = min(hits, key=lambda h: h[0]) if hits else (None, None)
        if base_rule is None and rules:
            base_rule = " / ".join(rules) + " (never crossed)"
        a_ts = pd.Timestamp(first.timestamp) if first else None
        rows.append(
            {
                "fault": fault["fault"],
                "gt_onset": onset,
                "detected": first is not None,
                "first_alert_ts": a_ts,
                "first_alert_type": first.type if first else None,
                "baseline_rule": base_rule,
                "baseline_ts": base_ts,
                "lead_vs_baseline_h": _hours(base_ts - a_ts) if (base_ts is not None and a_ts is not None) else float("nan"),
                "lead_vs_onset_h": _hours(onset - a_ts) if a_ts is not None else float("nan"),
                "detector": first.detector if first else None,
            }
        )
    return pd.DataFrame(rows, columns=COLUMNS)
