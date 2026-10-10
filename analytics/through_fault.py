"""Through-fault stress tracker. OWNER: Agent A. STUB.

Contract:
    detect(events, thresholds) -> list[Alert]
    stress_table(events, thresholds) -> pd.DataFrame     # per event + cumulative I2t, severity class
Reads the EVENT table (contracts.canonical.EVENT_COLUMNS), never the 15-minute trend: faults last
milliseconds to seconds and are invisible in 15-minute averages.
Classes: moderate >= moderate_pu, severe >= severe_pu. Rule: 1 severe OR moderate_count moderate events
since reset -> alert type through_fault_stress recommending a short-circuit impedance (%X) test.
Each qualifying event also yields a through_fault alert.
Empty events -> [].
"""
from __future__ import annotations

import pandas as pd

from contracts.models import Alert


def detect(events: pd.DataFrame, thresholds: dict) -> list[Alert]:
    return []


def stress_table(events: pd.DataFrame, thresholds: dict) -> pd.DataFrame:
    return pd.DataFrame()
