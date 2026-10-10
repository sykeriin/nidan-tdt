"""Through-fault stress tracker. OWNER: Agent A.

Contract:
    detect(events, thresholds, reset_at=None) -> list[Alert]
    stress_table(events, thresholds, reset_at=None) -> pd.DataFrame     # per event + cumulative I2t, class
Reads the EVENT table (contracts.canonical.EVENT_COLUMNS), never the 15-minute trend: faults last
milliseconds to seconds and are invisible in 15-minute averages.
Classes: moderate >= moderate_pu, severe >= severe_pu. Rule: 1 severe OR moderate_count moderate events
since reset -> alert type through_fault_stress recommending a short-circuit impedance (%X) test.
Each event at or above moderate also yields a through_fault alert. Events at or before reset_at are ignored.
Empty events -> [].
"""
from __future__ import annotations

import pandas as pd

from analytics.common import make_alert, strip_quarantined
from contracts.models import Alert

COLUMNS = [
    "timestamp", "peak_pu", "duration_ms", "i2t_pu2s", "cum_i2t_pu2s", "severity_class",
    "moderate_count_since_reset", "triggered",
]


def _prepare(events: pd.DataFrame, reset_at: pd.Timestamp | None) -> pd.DataFrame:
    if events is None or events.empty or "peak_pu" not in events.columns or "timestamp" not in events.columns:
        return pd.DataFrame(columns=list(events.columns) if events is not None else [])
    ev = strip_quarantined(events)
    if "event_type" in ev.columns:
        ev = ev[ev["event_type"] == "through_fault"]
    ev = ev.sort_values("timestamp").reset_index(drop=True)
    if reset_at is not None:
        ev = ev[pd.to_datetime(ev["timestamp"]) > pd.Timestamp(reset_at)].reset_index(drop=True)
    return ev


def stress_table(events: pd.DataFrame, thresholds: dict, reset_at: pd.Timestamp | None = None) -> pd.DataFrame:
    """One row per through-fault event. `triggered` is True from the event that satisfies the stress rule."""
    ev = _prepare(events, reset_at)
    if ev.empty:
        return pd.DataFrame(columns=COLUMNS)
    cfg = thresholds["operating"]["through_fault"]
    peak = pd.to_numeric(ev["peak_pu"], errors="coerce")
    dur = pd.to_numeric(ev.get("duration_ms"), errors="coerce")
    i2t = pd.to_numeric(ev["i2t_pu2s"], errors="coerce") if "i2t_pu2s" in ev.columns else pd.Series(float("nan"), index=ev.index)
    i2t = i2t.fillna(peak**2 * dur / 1000.0)
    cls = pd.Series("minor", index=ev.index)
    cls[peak >= cfg["moderate_pu"]] = "moderate"
    cls[peak >= cfg["severe_pu"]] = "severe"
    mod_count = (cls != "minor").cumsum()
    severe_seen = (cls == "severe").cummax()
    return pd.DataFrame(
        {
            "timestamp": ev["timestamp"], "peak_pu": peak, "duration_ms": dur, "i2t_pu2s": i2t,
            "cum_i2t_pu2s": i2t.cumsum(), "severity_class": cls,
            "moderate_count_since_reset": mod_count,
            "triggered": severe_seen | (mod_count >= cfg["moderate_count"]),
        }
    )[COLUMNS]


def detect(events: pd.DataFrame, thresholds: dict, reset_at: pd.Timestamp | None = None) -> list[Alert]:
    tbl = stress_table(events, thresholds, reset_at)
    if tbl.empty:
        return []
    ev = _prepare(events, reset_at)
    cfg = thresholds["operating"]["through_fault"]
    alerts: list[Alert] = []
    for i, row in tbl.iterrows():
        sim = bool(ev["simulated"].iloc[i]) if "simulated" in ev.columns else True
        if row["severity_class"] != "minor":
            severe = row["severity_class"] == "severe"
            alerts.append(
                make_alert(
                    row["timestamp"], "through_fault", "critical" if severe else "warning", "rule",
                    value=row["peak_pu"], threshold=cfg["severe_pu"] if severe else cfg["moderate_pu"],
                    explanation=(
                        f"{row['severity_class'].capitalize()} through-fault: peak {row['peak_pu']:.1f} pu for "
                        f"{row['duration_ms']:.0f} ms (I2t {row['i2t_pu2s']:.2f} pu2.s)."
                    ),
                    simulated=sim,
                )
            )
    hit = tbl.index[tbl["triggered"]]
    if len(hit):
        i = hit[0]
        row = tbl.loc[i]
        sim = bool(ev["simulated"].iloc[i]) if "simulated" in ev.columns else True
        alerts.append(
            make_alert(
                row["timestamp"], "through_fault_stress", "critical", "rule",
                value=row["cum_i2t_pu2s"],
                explanation=(
                    f"Through-fault stress rule met: 1 severe or {cfg['moderate_count']} moderate events since "
                    f"reset ({int(row['moderate_count_since_reset'])} qualifying so far, cumulative I2t "
                    f"{row['cum_i2t_pu2s']:.1f} pu2.s). Measure short-circuit impedance (%X) and compare with "
                    "the IS 1180 acceptance limit."
                ),
                simulated=sim,
            )
        )
    return sorted(alerts, key=lambda a: a.timestamp)
