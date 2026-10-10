"""Canonical column names. DRAFT, NOT FROZEN. P1 owns the real version.

Names follow FINAL_PRD.md section 3.1 / DATA_INGESTION_SPEC.md section 3. This draft exists only so
P3 code has something to import. Replace with P1's file when it exists.
"""
from __future__ import annotations

TREND_COLUMNS = [
    "timestamp",  # tz-aware, Asia/Kolkata
    "IR", "IY", "IB", "I_mean",  # A, LV side
    "IN",  # A, optional (neutral)
    "VR", "VY", "VB",  # V, phase-neutral, optional
    "S_kVA", "P_kW", "Q_kVAr", "PF", "freq_Hz",  # optional
    "loading_pct",  # % of rated
    "OTI_C", "WTI_C", "ATI_C",  # optional
    "amb_C",  # enriched ambient
    "RH_pct", "OLI_pct",  # optional
    "dq_flags",  # ';'-separated codes
    "source", "simulated",
]

# Added by the twin (PRD section 7.2). Analytics read these.
TWIN_COLUMNS = [
    "twin_oil_C", "twin_hs_C", "aging_rate", "days_aged_cum",
    "residual_oil_C",  # OTI_C - twin_oil_C, NaN in meter-only mode
    "fidelity_rmse_C",  # rolling 24 h
    "load_pu",
]

EVENT_COLUMNS = [
    "timestamp", "event_type",  # through_fault | trip | tamper | alarm | other
    "phase",  # R/Y/B/3ph/unknown
    "peak_pu", "duration_ms", "i2t_pu2s",
    "source", "simulated",
]

# Columns whose names start with these prefixes must NEVER reach detectors.
QUARANTINE_PREFIXES = ("gt_", "alarm_")

# Keys of the capability matrix (DATA_INGESTION_SPEC.md section 2.9). Draft vocabulary.
CAPABILITY_KEYS = [
    "thermal_twin", "residual", "hotspot_wti", "unbalance_current", "voltage_quality",
    "neutral_current", "oil_level", "through_fault", "breathing", "aging_rul", "lead_time",
]
