"""Step 9 CAPABILITY MATRIX (spec §2.9). Missing data turns features off; it never crashes the app."""
import pandas as pd

MIN_COVERAGE = 0.5  # a channel counts as present when >= 50 % of rows have it


def _present(df, col):
    return col in df and df[col].notna().mean() >= MIN_COVERAGE


def _measured(df, col):
    flags = df["dq_flags"] if "dq_flags" in df else pd.Series("", index=df.index)
    return _present(df, col) and not flags.str.contains(f"DERIVED_{col}(?:;|$)", regex=True).any()


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
