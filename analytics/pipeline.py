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

from analytics import electrical, health, oil, recommend, residual, rules, through_fault
from analytics.common import strip_quarantined
from contracts.canonical import QUARANTINE_PREFIXES
from contracts.models import AnalysisResult, TwinState


def _clean(frame: pd.DataFrame) -> pd.DataFrame:
    clean = strip_quarantined(frame)
    leaked = [c for c in clean.columns if str(c).startswith(QUARANTINE_PREFIXES)]
    if leaked:
        raise AssertionError(f"quarantined columns reached the detectors: {leaked}")
    return clean


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
    alerts = [
        *rules.detect(df, thresholds),
        *residual.detect(df, thresholds, reference=residual_reference),
        *electrical.detect(df, thresholds, caps),
        *oil.detect(df, thresholds),
        *through_fault.detect(ev, thresholds),
    ]
    alerts.sort(key=lambda a: a.timestamp)
    hi = health.compute(df, alerts, caps, thresholds)
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
