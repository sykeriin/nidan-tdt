"""Replay / IoT simulator (FINAL_PRD.md §12.2): iterate canonical rows as a live feed.

    for row in Replay(ds, speed=900):      # 900x: one 15-min row per second
        state = engine.step(row)

speed  = data-seconds per wall-second (None = as fast as possible). Sleeping is injectable for tests/dashboards.
seed   = fixed RNG for the optional comms-loss simulation (dropout); same seed -> same stream.
Rows keep their `simulated` flag; `source` becomes "replay" and `replay_of` keeps the original source.
"""
import time
from collections.abc import Callable, Iterator

import numpy as np
import pandas as pd

from contracts.models import Dataset


def _aware(x, tz) -> pd.Timestamp:
    """x as a Timestamp in the data's zone, whether it arrived naive (taken as that zone) or already tz-aware."""
    ts = pd.Timestamp(x)
    return ts.tz_localize(tz) if ts.tzinfo is None else ts.tz_convert(tz)


class Replay:
    def __init__(self, ds: Dataset | pd.DataFrame, speed: float | None = 60.0, seed: int = 0,
                 dropout: float = 0.0, start=None, end=None, sleep: Callable[[float], None] = time.sleep):
        trend = ds.trend if isinstance(ds, Dataset) else ds
        t = trend.sort_values("timestamp").reset_index(drop=True)
        if start is not None:
            t = t[t["timestamp"] >= _aware(start, t["timestamp"].dt.tz)]
        if end is not None:
            t = t[t["timestamp"] <= _aware(end, t["timestamp"].dt.tz)]
        self.trend = t.reset_index(drop=True)
        self.speed, self.seed, self.dropout, self._sleep = speed, seed, dropout, sleep
        self.mode = ds.mode if isinstance(ds, Dataset) else None

    def kept(self) -> np.ndarray:
        """Boolean mask of rows that survive the simulated comms loss (deterministic for a seed)."""
        if self.dropout <= 0:
            return np.ones(len(self.trend), bool)
        return np.random.default_rng(self.seed).random(len(self.trend)) >= self.dropout

    def __len__(self) -> int:
        return int(self.kept().sum())

    def __iter__(self) -> Iterator[dict]:
        rows = self.trend[self.kept()]
        prev = None
        for row in rows.to_dict("records"):
            ts = row["timestamp"]
            if self.speed and prev is not None:
                self._sleep(max((ts - prev).total_seconds(), 0) / self.speed)
            prev = ts
            row["replay_of"] = row.get("source")
            row["source"] = "replay"
            yield row
