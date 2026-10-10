"""Shared helpers for P3 analytics. Written by the lead, used by all detectors. Do not fork it.

If you need a new helper, add it here with a test in tests/test_common.py.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from contracts.canonical import QUARANTINE_PREFIXES
from contracts.models import Alert

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
    "drift_sensor": "data",        # slow drift impossible for the asset (e.g. oil level rising without a refill)
    "implausible_sensor": "data",  # twin physics says the reading can't be true (IMPLAUSIBLE_RISE, ATI_MISMATCH)
}


DEFAULT_ASSET_PATH = Path(__file__).resolve().parent.parent / "config" / "asset.yaml"


def load_thresholds(path: str | Path | None = None, asset: str | Path | dict | None = None) -> dict:
    """thresholds.yaml plus a `reference` block taken from the asset (asset.yaml or an adapter-resolved dict)."""
    with open(path or DEFAULT_THRESHOLDS_PATH, encoding="utf-8") as fh:
        th = yaml.safe_load(fh)
    a = asset if isinstance(asset, dict) else _read_asset(asset or DEFAULT_ASSET_PATH)
    lv = float(a.get("lv_voltage_V", 415.0))
    th["reference"] = {"i_rated_a": float(a["i_rated_A"]), "v_ln_nominal_v": lv / np.sqrt(3),
                       "estimated": a.get("nameplate_source") == "estimated"}
    return th


def _read_asset(path) -> dict:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return {k: (v["value"] if isinstance(v, dict) and "value" in v else v) for k, v in raw.items()}


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


def merge_by_time(mask: np.ndarray, ts: pd.Series, gap_h: float) -> np.ndarray:
    """Join True runs whose gap (end of one to start of the next, in time) is under gap_h hours.

    A chronic condition that dips under its clear level for a while (daily cycle, noise) is one episode, not many."""
    m = np.asarray(mask, dtype=bool).copy()
    t = pd.to_datetime(ts).to_numpy()
    found = runs(m)
    limit = np.timedelta64(int(gap_h * 3600), "s")
    for (_, prev_end), (next_start, _) in zip(found, found[1:]):
        if t[next_start] - t[prev_end] < limit:
            m[prev_end + 1 : next_start] = True
    return m


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
