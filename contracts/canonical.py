"""Canonical trend/event tables (DATA_INGESTION_SPEC.md §3). Everything downstream reads only these."""
import pandas as pd

TZ = "Asia/Kolkata"

# column -> unit. Order is the order written to disk.
TREND_COLUMNS = {
    "record_id": "-",        # snapshot mode only (per-record files without time)
    "timestamp": "tz-aware",
    "IR": "A", "IY": "A", "IB": "A", "I_mean": "A", "IN": "A",
    "VR": "V", "VY": "V", "VB": "V",            # phase-neutral
    "VRY": "V", "VYB": "V", "VBR": "V",          # line-line (optional, kept when measured)
    "S_kVA": "kVA", "P_kW": "kW", "Q_kVAr": "kVAr", "PF": "-", "freq_Hz": "Hz",
    "loading_pct": "%",
    "OTI_C": "C", "WTI_C": "C", "ATI_C": "C", "amb_C": "C",
    "RH_pct": "%", "OLI_pct": "%",
    "dq_flags": "codes", "source": "-", "simulated": "bool",
}
REQUIRED = ["timestamp", "I_mean", "loading_pct", "amb_C", "dq_flags", "source", "simulated"]
PREFIXES = ("alarm_", "gt_", "extra_")  # display-only / evaluation-only / raw view

EVENT_COLUMNS = ["timestamp", "event_type", "phase", "peak_pu", "duration_ms", "i2t_pu2s", "source", "simulated"]
EVENT_TYPES = {"through_fault", "trip", "tamper", "alarm", "other"}

SOURCES = {"generated_sim", "kaggle_real", "organizer", "replay", "live"}

DQ_CODES = {"DUP_IDENT", "DUP_CONFLICT", "GAP", "JUMP_OTI", "JUMP_WTI", "ATI_MISMATCH", "MERGE_CONFLICT",
            "IMPLAUSIBLE_RISE"}  # IMPLAUSIBLE_RISE: twin/plausibility.py
DQ_PREFIXES = ("RANGE_", "STUCK_", "NEG_", "IMPUTED_", "DERIVED_", "ASSUMED_")

# Physical ranges for RANGE_<COL> (spec §2.8, configurable here)
RANGES = {
    "OTI_C": (-10, 150), "WTI_C": (-10, 150), "ATI_C": (-10, 60),
    "VR": (100, 300), "VY": (100, 300), "VB": (100, 300),
    "PF": (-1, 1), "OLI_pct": (0, 100), "RH_pct": (0, 100), "freq_Hz": (45, 55),
}


def empty_events() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in EVENT_COLUMNS})


def is_canonical(col: str) -> bool:
    return col in TREND_COLUMNS or col.startswith(PREFIXES)


def validate(trend: pd.DataFrame, events: pd.DataFrame | None = None) -> list[str]:
    """Return a list of contract violations (empty = valid)."""
    p = []
    snapshot = "record_id" in trend.columns and "timestamp" not in trend.columns
    for c in REQUIRED:
        if c not in trend.columns and not (snapshot and c == "timestamp"):
            p.append(f"missing required column {c}")
    if snapshot and trend["record_id"].duplicated().any():
        p.append("duplicate record_id")
    for c in trend.columns:
        if not is_canonical(c):
            p.append(f"non-canonical column {c}")
    if "timestamp" in trend.columns:
        ts = trend["timestamp"]
        if getattr(ts.dt, "tz", None) is None:
            p.append("timestamp is not tz-aware")
        if not ts.is_monotonic_increasing:
            p.append("timestamp not sorted")
        if ts.duplicated().any():
            p.append("duplicate timestamps")
    if "source" in trend.columns and not set(trend["source"].dropna().unique()) <= SOURCES:
        p.append(f"unknown source values {set(trend['source'].unique()) - SOURCES}")
    if "dq_flags" in trend.columns:
        codes = {c for s in trend["dq_flags"].dropna() for c in str(s).split(";") if c}
        bad = {c for c in codes if c not in DQ_CODES and not c.startswith(DQ_PREFIXES)}
        if bad:
            p.append(f"unknown dq codes {bad}")
    if events is not None and len(events):
        for c in EVENT_COLUMNS:
            if c not in events.columns:
                p.append(f"events missing {c}")
        if "event_type" in events.columns and not set(events["event_type"]) <= EVENT_TYPES:
            p.append("unknown event_type")
    return p
