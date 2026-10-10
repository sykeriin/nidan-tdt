"""Oil level: low level, slow leak vs sudden theft. OWNER: Agent A.

Contract:
    detect(df, thresholds) -> list[Alert]
Reads: OLI_pct (and OTI_C / twin_oil_C only to confirm "no thermal cause").
Emits: oil_low, oil_leak (slow decline over hours/days), oil_theft (a step of at least
thresholds.operating.theft.step_points within window_h, no matching thermal cause; night events flagged).
Return [] if OLI_pct is absent or all NaN.
"""
from __future__ import annotations

import pandas as pd

from analytics.common import hysteresis_mask, make_alert, runs, step_hours, strip_quarantined
from contracts.models import Alert

# Not in thresholds.yaml. A sustained decline of at least this many percentage points over LEAK_WINDOW_H,
# with no theft-sized step inside the window, is reported as a slow leak.
LEAK_DECLINE_POINTS = 3.0
LEAK_WINDOW_H = 24.0
# Oil temperature move over the theft window that would explain a level change thermally.
THERMAL_CAUSE_DELTA_C = 5.0
NIGHT_START_H, NIGHT_END_H = 22, 6


def _is_night(ts: pd.Timestamp) -> bool:
    return ts.hour >= NIGHT_START_H or ts.hour < NIGHT_END_H


def _temperature(df: pd.DataFrame) -> pd.Series | None:
    for name in ("OTI_C", "twin_oil_C"):
        if name in df.columns:
            s = pd.to_numeric(df[name], errors="coerce")
            if not s.isna().all():
                return s
    return None


def detect(df: pd.DataFrame, thresholds: dict) -> list[Alert]:
    df = strip_quarantined(df).reset_index(drop=True)
    if len(df) < 2 or "OLI_pct" not in df.columns or "timestamp" not in df.columns:  # interval undefined below 2 rows
        return []
    lvl = pd.to_numeric(df["OLI_pct"], errors="coerce")
    if lvl.isna().all():
        return []
    op = thresholds["operating"]
    clear = op.get("hysteresis_clear_fraction", 0.95)
    sim = lambda i: bool(df["simulated"].iloc[i]) if "simulated" in df.columns else True  # noqa: E731
    ts = pd.to_datetime(df["timestamp"])
    h = step_hours(df)
    alerts: list[Alert] = []

    low = op["oil_level_pct"]["low"]
    for start, _ in runs(hysteresis_mask(lvl.to_numpy(), low, clear, "low")):
        alerts.append(
            make_alert(
                ts.iloc[start], "oil_low", "warning", "rule", value=lvl.iloc[start], threshold=low,
                explanation=f"Oil level {lvl.iloc[start]:.1f} % fell to the {low:g} % low-level limit.",
                simulated=sim(start),
            )
        )

    step_pts, window_h = op["theft"]["step_points"], op["theft"]["window_h"]
    w = max(1, int(round(window_h / h)))
    drop = lvl.rolling(w + 1, min_periods=2).max() - lvl
    step_runs = runs((drop >= step_pts).to_numpy())
    temp = _temperature(df)
    for start, _ in step_runs:
        if temp is not None:
            moved = abs(temp.iloc[start] - temp.iloc[max(start - w, 0)])
            if not moved < THERMAL_CAUSE_DELTA_C:
                continue
            cause = f"oil temperature moved only {moved:.1f} C in the same window, so no thermal cause"
        else:
            cause = "no temperature channel to confirm or rule out a thermal cause"
        night = " The event happened at night (22:00-06:00)." if _is_night(ts.iloc[start]) else ""
        alerts.append(
            make_alert(
                ts.iloc[start], "oil_theft", "critical", "rule", value=drop.iloc[start], threshold=step_pts,
                explanation=(
                    f"Oil level dropped {drop.iloc[start]:.1f} points within {window_h:g} h; {cause}. "
                    f"Possible theft or tampering.{night}"
                ),
                simulated=sim(start),
            )
        )

    n_day = max(1, int(round(LEAK_WINDOW_H / h)))
    smooth = lvl.rolling(5, min_periods=1).median()
    decline = (smooth.shift(n_day) - smooth).to_numpy(copy=True)
    for start, _ in step_runs:
        decline[start : start + n_day + w + 1] = 0.0
    for start, _ in runs(hysteresis_mask(decline, LEAK_DECLINE_POINTS, clear)):
        alerts.append(
            make_alert(
                ts.iloc[start], "oil_leak", "warning", "rule", value=decline[start], threshold=LEAK_DECLINE_POINTS,
                explanation=(
                    f"Oil level fell {decline[start]:.1f} points over {LEAK_WINDOW_H:g} h with no sudden step. "
                    "Pattern of a slow leak."
                ),
                simulated=sim(start),
            )
        )

    return sorted(alerts, key=lambda a: a.timestamp)
