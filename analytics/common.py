"""Shared helpers for P3 analytics. Written by the lead, used by all detectors. Do not fork it.

If you need a new helper, add it here with a test in tests/test_common.py.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from contracts.models import Alert

# Columns that must never reach a detector: ground truth (gt_) and device alarm flags (alarm_).
# Kept here, not in contracts/canonical.py, because that file is owned by P1 and has no such constant.
QUARANTINE_PREFIXES = ("gt_", "alarm_")

DEFAULT_THRESHOLDS_PATH = Path(__file__).resolve().parent.parent / "config" / "thresholds.yaml"

# Alert type -> module. These are the only alert types P3 emits in the first pass.
# Modules follow contracts/models.py: overloading | insulation | short_circuit | electrical | oil | moisture | data
ALERT_MODULES: dict[str, str] = {
    "loading_high": "overloading",
    "overcurrent": "overloading",
    "hot_spot_high": "overloading",
    "top_oil_high": "overloading",
    "ageing_rate_high": "insulation",
    "residual_drift": "insulation",
    "current_unbalance": "electrical",
    "voltage_unbalance": "electrical",
    "voltage_high": "electrical",
    "voltage_low": "electrical",
    "oil_low": "oil",
    "oil_leak": "oil",
    "oil_theft": "oil",
    "through_fault": "short_circuit",
    "through_fault_stress": "short_circuit",
    "jump_sensor": "data",
    "range_sensor": "data",
    "stuck_sensor": "data",
    "dead_channel": "data",
}


def load_thresholds(path: str | Path | None = None) -> dict:
    with open(path or DEFAULT_THRESHOLDS_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def strip_quarantined(df: pd.DataFrame) -> pd.DataFrame:
    """Drop ground-truth (gt_*) and device-alarm (alarm_*) columns. Detectors must never see them."""
    keep = [c for c in df.columns if not c.startswith(QUARANTINE_PREFIXES)]
    return df[keep]


def step_hours(df: pd.DataFrame) -> float:
    """Median sampling interval in hours."""
    ts = pd.to_datetime(df["timestamp"])
    return float(ts.diff().dropna().median() / pd.Timedelta(hours=1))


def make_alert(
    ts: pd.Timestamp,
    type: str,
    severity: str,
    detector: str,
    *,
    value: float | None = None,
    threshold: float | None = None,
    explanation: str = "",
    origin: str = "asset",
    simulated: bool = True,
) -> Alert:
    """Build an Alert with a deterministic id. recommendation_id and lead_time_h are filled later."""
    if type not in ALERT_MODULES:
        raise ValueError(f"unknown alert type {type!r}; add it to ALERT_MODULES")
    ts = pd.Timestamp(ts)
    return Alert(
        id=f"{type}-{ts:%Y%m%dT%H%M}",
        timestamp=ts,
        module=ALERT_MODULES[type],
        type=type,
        severity=severity,
        origin=origin,
        detector=detector,
        value=None if value is None else float(value),
        threshold=None if threshold is None else float(threshold),
        explanation=explanation,
        recommendation_id=None,
        simulated=simulated,
        lead_time_h=None,
    )


def hysteresis_mask(
    values: np.ndarray | pd.Series,
    trip: float,
    clear_fraction: float = 0.95,
    direction: str = "high",
) -> np.ndarray:
    """Boolean mask that turns on at the trip level and only turns off after a clear margin.

    direction="high": on when value >= trip, off when value < trip * clear_fraction.
    direction="low":  on when value <= trip, off when value > trip * (2 - clear_fraction).
    NaN samples keep the previous state.
    """
    v = np.asarray(values, dtype=float)
    out = np.zeros(len(v), dtype=bool)
    state = False
    clear_hi = trip * clear_fraction
    clear_lo = trip * (2.0 - clear_fraction)
    for i, x in enumerate(v):
        if np.isnan(x):
            out[i] = state
            continue
        if direction == "high":
            if not state and x >= trip:
                state = True
            elif state and x < clear_hi:
                state = False
        else:
            if not state and x <= trip:
                state = True
            elif state and x > clear_lo:
                state = False
        out[i] = state
    return out


def persistent_mask(mask: np.ndarray, min_steps: int) -> np.ndarray:
    """Keep only runs of True that last at least min_steps samples."""
    m = np.asarray(mask, dtype=bool)
    out = np.zeros_like(m)
    for start, end in runs(m):
        if end - start + 1 >= min_steps:
            out[start : end + 1] = True
    return out


def runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Inclusive (start, end) index pairs of consecutive True runs."""
    m = np.asarray(mask, dtype=bool)
    if not m.any():
        return []
    padded = np.concatenate([[False], m, [False]])
    d = np.diff(padded.astype(int))
    starts = np.where(d == 1)[0]
    ends = np.where(d == -1)[0] - 1
    return list(zip(starts.tolist(), ends.tolist()))
