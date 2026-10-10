"""Rule-based threshold alarms with hysteresis. OWNER: Agent A (detectors). STUB.

Contract:
    detect(df, thresholds) -> list[Alert]
Reads: load_pu (or loading_pct/100), I_mean, OTI_C and/or twin_oil_C, twin_hs_C (or WTI_C), aging_rate.
Emits alert types: loading_high, overcurrent, top_oil_high, hot_spot_high, ageing_rate_high.
Must call strip_quarantined(df) first. One alert per episode (at the first sample of a run).
"""
from __future__ import annotations

import pandas as pd

from contracts.models import Alert


def detect(df: pd.DataFrame, thresholds: dict) -> list[Alert]:
    return []
