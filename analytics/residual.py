"""Residual detector: measured oil temperature drifting from the twin. OWNER: Agent A. STUB.

Contract:
    calibrate(normal_df, thresholds) -> dict           # mean, sigma, trip level from the Normal scenario
    detect(df, thresholds, reference=None) -> list[Alert]
Reads: residual_oil_C. Emits alert type: residual_drift (detector="residual").
Threshold = reference mean + sigma_mult * sigma, persistent for persist_h (thresholds.operating.residual).
If residual_oil_C is all NaN (meter-only mode) return [].
"""
from __future__ import annotations

import pandas as pd

from contracts.models import Alert


def calibrate(normal_df: pd.DataFrame, thresholds: dict) -> dict:
    return {}


def detect(df: pd.DataFrame, thresholds: dict, reference: dict | None = None) -> list[Alert]:
    return []
