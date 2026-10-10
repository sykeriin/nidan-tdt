"""Oil level: low level, slow leak vs sudden theft. OWNER: Agent A. STUB.

Contract:
    detect(df, thresholds) -> list[Alert]
Reads: OLI_pct (and residual_oil_C / OTI_C only to confirm "no thermal cause").
Emits: oil_low, oil_leak (slow decline over hours/days), oil_theft (a step of at least
thresholds.operating.theft.step_points within window_h, no matching thermal cause; flag night events).
Return [] if OLI_pct is absent or all NaN.
"""
from __future__ import annotations

import pandas as pd

from contracts.models import Alert


def detect(df: pd.DataFrame, thresholds: dict) -> list[Alert]:
    return []
