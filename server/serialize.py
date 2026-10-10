"""JSON-safe conversion and chart downsampling. Presentation only: no analytics here."""
from __future__ import annotations

import dataclasses
import math
from datetime import date, datetime

import numpy as np
import pandas as pd

MAX_POINTS = 2000


def plain(o):
    """Timestamps -> ISO 8601 with offset, NaN/NaT -> None, numpy -> Python numbers, dataclasses -> dicts."""
    if o is None or o is pd.NaT:
        return None
    if isinstance(o, pd.Timestamp):
        return o.isoformat()
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else f
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return {f.name: plain(getattr(o, f.name)) for f in dataclasses.fields(o)}
    if isinstance(o, pd.DataFrame):
        return table(o)
    if isinstance(o, dict):
        return {str(k): plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set, np.ndarray, pd.Series)):
        return [plain(v) for v in o]
    return o


def table(df: pd.DataFrame) -> dict:
    return {"columns": [str(c) for c in df.columns], "rows": [plain(r) for r in df.to_dict("records")]}


def time_range(df: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    if "timestamp" not in df or df.empty:
        return df
    ts = df["timestamp"]
    tz = ts.dt.tz
    if start is not None:
        df = df[ts >= _aware(start, tz)]
        ts = df["timestamp"]
    if end is not None:
        df = df[ts <= _aware(end, tz)]
    return df


def _aware(t, tz) -> pd.Timestamp:
    t = pd.Timestamp(t)
    return t.tz_localize(tz) if t.tzinfo is None and tz is not None else t


def downsample(ts: pd.Series, v: pd.Series, max_points: int = MAX_POINTS) -> tuple[list, list]:
    """Min-max bucketing: keeps each bucket's extremes (peaks and alarms survive), <= max_points samples."""
    ok = v.notna().to_numpy()
    t, x = ts.to_numpy()[ok], v.to_numpy(dtype=float)[ok]
    n = len(x)
    if n <= max_points:
        idx = np.arange(n)
    else:
        buckets = max_points // 2
        edges = np.linspace(0, n, buckets + 1).astype(int)
        idx = np.unique(np.concatenate([[s + int(np.argmin(x[s:e])), s + int(np.argmax(x[s:e]))]
                                        for s, e in zip(edges[:-1], edges[1:]) if e > s]))
    return [pd.Timestamp(t[i]).isoformat() for i in idx], [plain(x[i]) for i in idx]


def series(df: pd.DataFrame, max_points: int = MAX_POINTS, skip=("timestamp",)) -> tuple[dict, bool]:
    out, down = {}, False
    if "timestamp" not in df or df.empty:
        return out, down
    for c in df.columns:
        if c in skip or c.startswith(("gt_", "alarm_")):
            continue
        s = df[c]
        if s.dtype == bool:
            s = s.astype(float)
        if not pd.api.types.is_numeric_dtype(s) or s.isna().all():
            continue
        t, v = downsample(df["timestamp"], s, max_points)
        down |= len(v) < int(s.notna().sum())
        out[c] = {"t": t, "v": v}
    return out, down
