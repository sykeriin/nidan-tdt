"""Lead time vs a plain-threshold baseline. OWNER: Agent C (proof). STUB.

Contract:
    baseline_crossings(df, thresholds) -> dict[str, pd.Timestamp | None]
        first time each plain absolute threshold is crossed (the "dumb" baseline, no twin)
    lead_times(alerts, ground_truth, df, thresholds) -> pd.DataFrame
        one row per ground-truth fault: fault, gt_onset, first_alert_ts, baseline_ts,
        lead_vs_baseline_h, lead_vs_onset_h (negative = detected after onset), detector
`ground_truth` comes from tests.mock_data.ground_truth(scenario) (and later from P2's generator).
Ground truth is used ONLY here, never by detectors.
"""
from __future__ import annotations

import pandas as pd

from contracts.models import Alert


def baseline_crossings(df: pd.DataFrame, thresholds: dict) -> dict:
    return {}


def lead_times(alerts: list[Alert], ground_truth: list[dict], df: pd.DataFrame, thresholds: dict) -> pd.DataFrame:
    return pd.DataFrame()
