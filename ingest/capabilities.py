"""Step 9 CAPABILITY MATRIX (spec §2.9). Missing data turns features off; it never crashes the app."""
import pandas as pd

MIN_COVERAGE = 0.5  # a channel counts as present when >= 50 % of rows have it


def _present(df, col):
    return col in df and df[col].notna().mean() >= MIN_COVERAGE


def _measured(df, col):
    flags = df["dq_flags"] if "dq_flags" in df else pd.Series("", index=df.index)
    return _present(df, col) and not flags.str.contains(f"DERIVED_{col}(?:;|$)", regex=True).any()


SNAPSHOT_DISABLED = {
    "ageing_rul": "needs a time axis: ageing accumulates over time (per-record ageing rate at the operating point is shown)",
    "residual_fidelity": "rolling fidelity needs a time series (per-record residual is shown)",
    "lead_time_eval": "lead time needs time",
    "replay": "nothing to replay without time",
    "oil_leak_theft": "leak vs theft needs the oil level over time",
    "breathing_index": "needs daily temperature swing",
    "through_fault": "needs an event log",
}


def compute_snapshot(records: pd.DataFrame) -> tuple[dict[str, bool], str, pd.DataFrame, dict]:
    """Dataset-level capabilities, per-record capability matrix and disabled-feature messages for snapshot mode."""
    def has(c):
        return records[c].notna() if c in records else pd.Series(False, index=records.index)
    flags = records["dq_flags"] if "dq_flags" in records else pd.Series("", index=records.index)
    per = pd.DataFrame({
        "record_id": records["record_id"],
        "thermal_twin": has("I_mean") & has("amb_C"),
        "residual": has("I_mean") & has("amb_C") & has("OTI_C"),
        "unbalance": has("IR") & has("IY") & has("IB") & ~flags.str.contains("DERIVED_IR"),
        "voltage_quality": has("VR") & has("VY") & has("VB"),
        "oil_level": has("OLI_pct"),
    })
    caps = {k: bool(per[k].mean() >= MIN_COVERAGE) for k in per.columns if k != "record_id"}
    caps.update({k: False for k in SNAPSHOT_DISABLED})
    mode = "snapshot" if caps["thermal_twin"] else "data_only"
    return caps, mode, per, dict(SNAPSHOT_DISABLED)


def compute(trend: pd.DataFrame, events: pd.DataFrame) -> tuple[dict[str, bool], str]:
    has_current = _present(trend, "I_mean")
    has_amb = _present(trend, "amb_C")
    twin = has_current and has_amb
    oti = _present(trend, "OTI_C")
    caps = {
        "thermal_twin": twin,
        "residual_fidelity": twin and oti,
        "wti_check": _present(trend, "WTI_C"),
        "unbalance": all(_measured(trend, c) for c in ("IR", "IY", "IB")),
        "voltage_quality": all(_present(trend, c) for c in ("VR", "VY", "VB")),
        "neutral_measured": _present(trend, "IN"),
        "oil_leak_theft": _present(trend, "OLI_pct"),
        "through_fault": len(events) > 0 or any(c.endswith("_max") for c in trend.columns),
        "breathing_index": (oti or twin) and _present(trend, "RH_pct"),
        "ageing_rul": twin,
        "lead_time_eval": any(c.startswith("gt_") for c in trend.columns),
    }
    caps = {k: bool(v) for k, v in caps.items()}
    mode = "data_only" if not twin else "full" if oti else "meter_only"
    return caps, mode
