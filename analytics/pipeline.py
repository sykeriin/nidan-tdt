"""Pipeline: one call that runs every detector. OWNER: Agent B (scoring and advice).

Contract (FINAL_PRD section 12.2):
    analyze(df_twin, events, caps, thresholds, residual_reference=None) -> AnalysisResult
    class StreamAnalyzer:  update(state, new_events) -> AnalysisResult
The optional fifth argument (a residual.calibrate() result) is the only extension to the PRD signature.
Order: strip_quarantined -> assert no gt_/alarm_ column remains -> rules, residual, electrical, oil,
through_fault -> sort alerts by time -> health.compute -> recommend.build. RUL belongs to P2 and is None.
"""
from __future__ import annotations

import pandas as pd

from analytics import electrical, health, oil, recommend, residual, rules, sensor_faults, standards, through_fault
from analytics.common import strip_quarantined
from contracts.canonical import QUARANTINE_PREFIXES
from contracts.models import AnalysisResult, TwinState


def _clean(frame: pd.DataFrame) -> pd.DataFrame:
    clean = strip_quarantined(frame)
    leaked = [c for c in clean.columns if str(c).startswith(QUARANTINE_PREFIXES)]
    if leaked:
        raise AssertionError(f"quarantined columns reached the detectors: {leaked}")
    return clean


# Alerts whose level depends on the rating (per-unit load) or on a twin driven by it. With a rating estimated from
# the data (no nameplate) they are indicative only: severity info, never a finding, never the Health Index cap.
RATING_DEPENDENT = {"loading_high", "overcurrent", "hot_spot_high", "top_oil_high", "ageing_rate_high"}
ESTIMATED_NOTE = " Rating estimated from data (no nameplate): indicative only."


def _estimated_rating(alerts: list, thresholds: dict) -> list:
    if not thresholds.get("reference", {}).get("estimated"):
        return alerts
    import dataclasses
    return [dataclasses.replace(a, severity="info", explanation=a.explanation + ESTIMATED_NOTE)
            if a.type in RATING_DEPENDENT and a.origin == "asset" else a for a in alerts]


def _last_fidelity(df: pd.DataFrame) -> float | None:
    if "fidelity_rmse_C" not in df.columns:
        return None
    vals = pd.to_numeric(df["fidelity_rmse_C"], errors="coerce").dropna()
    return float(vals.iloc[-1]) if len(vals) else None


def analyze(
    df_twin: pd.DataFrame,
    events: pd.DataFrame,
    caps: dict,
    thresholds: dict,
    residual_reference: dict | None = None,
) -> AnalysisResult:
    df = _clean(df_twin)
    ev = _clean(events) if events is not None else pd.DataFrame()
    sensor_eps = sensor_faults.episodes(df, thresholds, caps)
    # Channels the asset detectors must not read: a top-oil channel that failed the twin's plausibility check
    # (caps residual_fidelity False while OTI is present) and channels the sensor layer judged unreliable.
    # The sensor-fault layer above still sees them, so a bad sensor produces sensor alerts only.
    untrusted = sensor_faults.unreliable_channels(df, sensor_eps)
    if not caps.get("residual_fidelity", True):
        untrusted.add("OTI_C")
    adf = df.drop(columns=[c for c in untrusted if c in df.columns])
    alerts = [
        *sensor_faults.relabel(
            [
                *rules.detect(adf, thresholds),
                *(residual.detect(adf, thresholds, reference=residual_reference)
                  if caps.get("residual_fidelity", True) else []),
                *electrical.detect(adf, thresholds, caps),
                *oil.detect(adf, thresholds),
                *standards.detect(adf, ev, thresholds),
            ],
            sensor_eps,  # asset alerts caused by a flagged sensor sample become origin="sensor" (not deleted)
        ),
        *through_fault.detect(ev, thresholds),
        *sensor_faults.alerts_of(sensor_eps),
    ]
    alerts = _estimated_rating(alerts, thresholds)
    alerts.sort(key=lambda a: a.timestamp)
    hi = health.compute(adf, alerts, caps, thresholds)
    recs = recommend.build(alerts, hi, thresholds)
    return AnalysisResult(alerts=alerts, recommendations=recs, health=hi, rul=None, fidelity_rmse_C=_last_fidelity(df))


class StreamAnalyzer:
    """Streaming wrapper: buffers every row and event and re-runs analyze() on the buffer.

    Simple and guaranteed identical to the batch result. Cost is O(n) per update (O(n^2) over a stream),
    acceptable for demo-length replays; a rolling window or incremental detectors would be needed beyond that.
    """

    def __init__(self, caps: dict, thresholds: dict, residual_reference: dict | None = None):
        self.caps = caps
        self.thresholds = thresholds
        self.residual_reference = residual_reference
        self._rows: list[dict] = []
        self._events: list[dict] = []

    def update(self, state: TwinState, new_events: list[dict]) -> AnalysisResult:
        self._rows.append({**state.row, **state.twin, "timestamp": state.timestamp})
        self._events.extend(new_events or [])
        return analyze(
            pd.DataFrame(self._rows), pd.DataFrame(self._events), self.caps, self.thresholds, self.residual_reference
        )


SNAPSHOT_SPACING = pd.Timedelta(days=30)  # > every health window: each record is scored on its own


def analyze_snapshot(records: pd.DataFrame, caps: dict, thresholds: dict) -> pd.DataFrame:
    """Snapshot mode (records without time): per-record Health Index at each steady-state operating point, ranked
    worst first. Uses the same sub-score curves and weights as health.compute_series; time-based detectors
    (episodes, drift, leak/theft, lead time) do not apply. A top-oil channel that failed plausibility is not read."""
    df = _clean(records).reset_index(drop=True)
    if not caps.get("residual_fidelity", True) or df.get("implausible_rise", pd.Series(False)).mean() > 0.5:
        df = df.drop(columns=[c for c in ("OTI_C",) if c in df.columns])
    df.insert(0, "timestamp", pd.Timestamp("2000-01-01", tz="Asia/Kolkata") + SNAPSHOT_SPACING * pd.RangeIndex(len(df)))
    s = health.compute_series(df, [], caps, thresholds).drop(columns=["timestamp", "capped"])
    keep = [c for c in ("record_id", "load_pu", "amb_C", "OTI_C", "twin_oil_C", "twin_hs_C", "residual_oil_C",
                        "implausible_rise", "dq_flags") if c in records.columns]
    out = pd.concat([records[keep].reset_index(drop=True), s], axis=1)
    out = out.sort_values("score", kind="stable").reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    return out
