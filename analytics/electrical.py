"""Electrical quality: current/voltage unbalance, over/under voltage. OWNER: Agent A.

Contract:
    unbalance_pct(df) -> pd.Series                      # current unbalance %, NaN if phases missing
    detect(df, thresholds, caps) -> list[Alert]
Current unbalance % = max |I_phase - I_mean| / I_mean * 100. Voltage unbalance likewise.
Emits: current_unbalance, voltage_unbalance, voltage_high, voltage_low.
Voltage pu uses thresholds["reference"]["v_ln_nominal_v"].
No neutral-current or earthing claim is made. Gated on caps unbalance_current / voltage_quality.
"""
from __future__ import annotations

import pandas as pd

from analytics.common import hysteresis_mask, make_alert, runs, strip_quarantined
from contracts.models import Alert

_I = ["IR", "IY", "IB"]
_V = ["VR", "VY", "VB"]


def _phases(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame | None:
    """Numeric phase columns, or None if any is absent or all NaN."""
    if any(c not in df.columns for c in cols):
        return None
    p = df[cols].apply(pd.to_numeric, errors="coerce")
    return None if p.isna().all().any() else p


def _unbalance(p: pd.DataFrame) -> pd.Series:
    mean = p.mean(axis=1, skipna=False)
    dev = p.sub(mean, axis=0).abs().max(axis=1)
    return (dev / mean.where(mean > 0) * 100.0).rename("unbalance_pct")


def unbalance_pct(df: pd.DataFrame) -> pd.Series:
    """Current unbalance %. NaN where a phase current is missing."""
    p = _phases(strip_quarantined(df), _I)
    if p is None:
        return pd.Series(float("nan"), index=df.index, name="unbalance_pct")
    return _unbalance(p)


def _sim(df: pd.DataFrame, i: int) -> bool:
    return bool(df["simulated"].iloc[i]) if "simulated" in df.columns else True


def _episodes(
    values: pd.Series, levels: list[tuple[float, str]], clear: float, direction: str = "high"
) -> list[tuple[int, float, str]]:
    found: dict[int, tuple[float, str]] = {}
    for trip, sev in levels:
        for start, _ in runs(hysteresis_mask(values.to_numpy(), trip, clear, direction)):
            found[start] = (trip, sev)
    return [(i, *found[i]) for i in sorted(found)]


def detect(df: pd.DataFrame, thresholds: dict, caps: dict) -> list[Alert]:
    df = strip_quarantined(df).reset_index(drop=True)
    if df.empty or "timestamp" not in df.columns:
        return []
    op = thresholds["operating"]
    clear = op.get("hysteresis_clear_fraction", 0.95)
    alerts: list[Alert] = []

    cur = _phases(df, _I) if caps.get("unbalance_current") else None
    if cur is not None:
        cu = op["current_unbalance_pct"]
        ub = _unbalance(cur)
        for i, trip, sev in _episodes(ub, [(cu["warning"], "warning"), (cu["alarm"], "critical")], clear):
            alerts.append(
                make_alert(
                    df["timestamp"].iloc[i], "current_unbalance", sev, "rule", value=ub.iloc[i], threshold=trip,
                    explanation=(
                        f"Phase current unbalance {ub.iloc[i]:.1f} % reached {trip:g} %. "
                        "Computed from R/Y/B line currents only; no neutral-current or earthing conclusion."
                    ),
                    simulated=_sim(df, i),
                )
            )

    vol = _phases(df, _V) if caps.get("voltage_quality") else None
    if vol is not None:
        vub = _unbalance(vol)
        trip = op["voltage_unbalance_pct"]["alarm"]
        for i, t, sev in _episodes(vub, [(trip, "critical")], clear):
            alerts.append(
                make_alert(
                    df["timestamp"].iloc[i], "voltage_unbalance", sev, "rule", value=vub.iloc[i], threshold=t,
                    explanation=f"Phase voltage unbalance {vub.iloc[i]:.2f} % reached {t:g} %.",
                    simulated=_sim(df, i),
                )
            )
        vpu = vol / thresholds["reference"]["v_ln_nominal_v"]
        for type_, series, trip, direction, word in (
            ("voltage_high", vpu.max(axis=1), op["voltage_pu"]["high"], "high", "Highest"),
            ("voltage_low", vpu.min(axis=1), op["voltage_pu"]["low"], "low", "Lowest"),
        ):
            for i, t, sev in _episodes(series, [(trip, "warning")], clear, direction):
                alerts.append(
                    make_alert(
                        df["timestamp"].iloc[i], type_, sev, "rule", value=series.iloc[i], threshold=t,
                        explanation=f"{word} phase voltage {series.iloc[i]:.3f} pu crossed {t:g} pu.",
                        simulated=_sim(df, i),
                    )
                )

    return sorted(alerts, key=lambda a: a.timestamp)
