"""Electrical quality: current/voltage unbalance, over/under voltage. OWNER: Agent A. STUB.

Contract:
    unbalance_pct(df) -> pd.Series                      # current unbalance %, NaN if phases missing
    detect(df, thresholds, caps) -> list[Alert]
Current unbalance % = max |I_phase - I_mean| / I_mean * 100. Voltage unbalance likewise.
Emits: current_unbalance, voltage_unbalance, voltage_high, voltage_low.
Voltage pu uses thresholds["reference"]["v_ln_nominal_v"].
Neutral: IN may be NaN; do NOT claim neutral current or earthing. If you add an unbalance-based proxy,
label it as a proxy in explanation text.
Disable (return []) when caps says the needed channels are absent.
"""
from __future__ import annotations

import pandas as pd

from contracts.models import Alert


def unbalance_pct(df: pd.DataFrame) -> pd.Series:
    return pd.Series(float("nan"), index=df.index)


def detect(df: pd.DataFrame, thresholds: dict, caps: dict) -> list[Alert]:
    return []
