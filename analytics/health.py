"""Health Index. OWNER: Agent B (scoring and advice). STUB.

Contract:
    compute_series(df, alerts, caps, thresholds) -> pd.DataFrame
        columns: timestamp, score, band, thermal, ageing, loading, electrical, integrity, fault_stress, capped
    compute(df, alerts, caps, thresholds) -> Health      # value at the last timestamp
Weights (FINAL_PRD section 8.8): thermal 30, ageing 25, loading 15, electrical quality 15, integrity 10,
fault stress 5. Weights renormalize over AVAILABLE sub-scores (caps). Piecewise-linear sub-scores from
thresholds. Weakest-link cap: any critical asset alarm caps score at 40. Bands: Green >= 80,
Yellow 60-79, Red < 60. Score always within 0..100.
"""
from __future__ import annotations

import pandas as pd

from contracts.models import Alert, Health


def compute_series(df: pd.DataFrame, alerts: list[Alert], caps: dict, thresholds: dict) -> pd.DataFrame:
    return pd.DataFrame()


def compute(df: pd.DataFrame, alerts: list[Alert], caps: dict, thresholds: dict) -> Health:
    return Health(score=100.0, band="Green", components={}, weights={}, capped=False)
