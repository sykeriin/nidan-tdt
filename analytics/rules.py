"""Rule-based threshold alarms with hysteresis. OWNER: Agent A (detectors).

Contract:
    detect(df, thresholds) -> list[Alert]
Reads: load_pu (or loading_pct/100), OTI_C and/or twin_oil_C, WTI_C and/or twin_hs_C, aging_rate.
Emits alert types: loading_high, overcurrent, top_oil_high, hot_spot_high, ageing_rate_high.
One alert per episode, stamped at the first sample of the run. A higher level that starts later in the
same episode raises its own (escalation) alert. Missing or all-NaN channels disable that rule.
"""
from __future__ import annotations

import pandas as pd

from analytics.common import hysteresis_mask, make_alert, runs, step_hours, strip_quarantined
from contracts.models import Alert

# Ageing-rate alarm level: 98 C hot-spot is ageing rate 1 (PRD section 9). Not in thresholds.yaml.
AGEING_RATE_LIMIT = 1.0
AGEING_AVG_H = 1.0


def _usable(df: pd.DataFrame, name: str) -> pd.Series | None:
    """Numeric column, or None if absent or all NaN."""
    if name not in df.columns:
        return None
    s = pd.to_numeric(df[name], errors="coerce")
    return None if s.isna().all() else s


def _sim(df: pd.DataFrame, i: int) -> bool:
    return bool(df["simulated"].iloc[i]) if "simulated" in df.columns else True


def _episodes(
    values: pd.Series, levels: list[tuple[float, str]], clear: float
) -> list[tuple[int, float, str]]:
    """(first index, trip level, severity) per episode. levels ascend in severity."""
    found: dict[int, tuple[float, str]] = {}
    for trip, sev in levels:
        for start, _ in runs(hysteresis_mask(values.to_numpy(), trip, clear)):
            found[start] = (trip, sev)
    return [(i, *found[i]) for i in sorted(found)]


def _emit(
    df: pd.DataFrame, values: pd.Series, levels: list[tuple[float, str]], clear: float,
    type_: str, label: str, unit: str, source: str,
) -> list[Alert]:
    out = []
    for i, trip, sev in _episodes(values, levels, clear):
        v = float(values.iloc[i])
        out.append(
            make_alert(
                df["timestamp"].iloc[i], type_, sev, "rule", value=v, threshold=trip,
                explanation=f"{label} {v:.2f} {unit} reached {trip:g} {unit} ({source}).",
                simulated=_sim(df, i),
            )
        )
    return out


def detect(df: pd.DataFrame, thresholds: dict) -> list[Alert]:
    df = strip_quarantined(df).reset_index(drop=True)
    if len(df) < 2 or "timestamp" not in df.columns:  # sampling interval undefined below 2 rows
        return []
    op = thresholds["operating"]
    clear = op.get("hysteresis_clear_fraction", 0.95)
    alerts: list[Alert] = []

    load = _usable(df, "load_pu")
    if load is None:
        pct = _usable(df, "loading_pct")
        load = None if pct is None else pct / 100.0
    if load is not None:
        lp = op["loading_pu"]
        alerts += _emit(
            df, load, [(lp["warning"], "warning"), (lp["alarm"], "critical")], clear,
            "loading_high", "Loading", "pu", "measured load",
        )
        alerts += _emit(
            df, load, [(op["overcurrent_pu"]["alarm"], "critical")], clear,
            "overcurrent", "Load current", "pu", "measured load",
        )

    oti = _usable(df, "OTI_C")
    oil, oil_src = (oti, "measured") if oti is not None else (_usable(df, "twin_oil_C"), "twin-estimated")
    if oil is not None:
        t = op["top_oil_c"]
        alerts += _emit(
            df, oil, [(t["warning"], "warning"), (t["critical"], "critical")], clear,
            "top_oil_high", "Top-oil temperature", "C", f"{oil_src} top oil",
        )

    wti = _usable(df, "WTI_C")
    hs, hs_src = (wti, "measured") if wti is not None else (_usable(df, "twin_hs_C"), "twin-estimated")
    if hs is not None:
        t = op["hot_spot_c"]
        alerts += _emit(
            df, hs, [(t["warning"], "warning"), (t["critical"], "critical")], clear,
            "hot_spot_high", "Hot-spot temperature", "C", f"{hs_src} hot spot",
        )

    rate = _usable(df, "aging_rate_actual")  # actual ageing (twin/engine.py) when present, else the twin rate
    if rate is None:
        rate = _usable(df, "aging_rate")
    if rate is not None:
        n = max(1, int(round(AGEING_AVG_H / step_hours(df))))
        avg = rate.rolling(n, min_periods=1).mean()
        alerts += _emit(
            df, avg, [(AGEING_RATE_LIMIT, "warning")], clear,
            "ageing_rate_high", "1 h mean ageing rate", "x normal", "twin-estimated",
        )

    return sorted(alerts, key=lambda a: a.timestamp)
