"""Step 8 VALIDATE -> boolean __dq_<CODE> columns (joined into dq_flags at the end). Nothing is deleted."""
import pandas as pd

from contracts.canonical import RANGES

TEMPS = ("OTI_C", "WTI_C", "ATI_C")
# ATI_C excluded: ambient is load-independent, so "flat while load moves" says nothing (ATI_MISMATCH covers it)
STUCK_COLS = ("OTI_C", "WTI_C", "OLI_pct", "IR", "IY", "IB", "VR", "VY", "VB")
NEG_COLS = ("IR", "IY", "IB", "IN", "S_kVA")
JUMP_LIMIT_C = 5.0        # per 15 min
STUCK_SAMPLES = 8
STUCK_LOAD_CHANGE = 0.10


def _or(df, code, mask):
    col = f"__dq_{code}"
    df[col] = (df[col] if col in df else False) | mask.fillna(False).astype(bool)


def validate_static(df: pd.DataFrame, i_rated: float | None = None) -> pd.DataFrame:
    """Checks that need no time axis: RANGE_*, NEG_* (also used by snapshot mode)."""
    df = df.copy()
    for col, (lo, hi) in RANGES.items():
        if col in df and df[col].notna().any():
            x = df[col]
            bad = (x < lo) | (x > hi)
            if col in TEMPS and x.median() > 5:
                bad |= x == 0          # exact 0.0 in a warm climate = sensor dropout
            _or(df, f"RANGE_{col}", bad)
    if i_rated:
        for col in ("IR", "IY", "IB"):
            if col in df:
                _or(df, f"RANGE_{col}", df[col] > 5 * i_rated)

    for col in NEG_COLS:
        if col in df:
            _or(df, f"NEG_{col}", df[col] < 0)
    return df


def validate(df: pd.DataFrame, interval: pd.Timedelta, i_rated: float | None = None) -> pd.DataFrame:
    df = validate_static(df, i_rated)
    dt = df["timestamp"].diff()
    gap = dt > 3 * interval
    _or(df, "GAP", gap)

    # jumps: change over max(dt, 15 min) scaled to 15 min; not across gaps
    win = dt.where(dt > pd.Timedelta("15min"), pd.Timedelta("15min"))
    for col, code in (("OTI_C", "JUMP_OTI"), ("WTI_C", "JUMP_WTI")):
        if col in df and df[col].notna().any():
            rate = df[col].diff().abs() / (win / pd.Timedelta("15min"))
            _or(df, code, (rate > JUMP_LIMIT_C) & ~gap)

    # stuck: unchanged for >= 8 samples while load changes > 10 %
    if "I_mean" in df:
        r = df["I_mean"].rolling(STUCK_SAMPLES)
        load_moves = (r.max() - r.min()) / r.mean().where(r.mean() > 0) > STUCK_LOAD_CHANGE
        for col in STUCK_COLS:
            if col not in df or df[col].isna().all() or df.get(f"__dq_DERIVED_{col}", pd.Series(False)).any():
                continue
            c = df[col].rolling(STUCK_SAMPLES)
            end = ((c.max() - c.min()) == 0) & load_moves
            mark = end[::-1].astype(float).rolling(STUCK_SAMPLES, min_periods=1).max()[::-1] > 0
            _or(df, f"STUCK_{col.split('_')[0]}", mark)

    return df


def flags_to_string(df: pd.DataFrame) -> pd.Series:
    cols = [c for c in df.columns if c.startswith("__dq_")]
    if not cols:
        return pd.Series("", index=df.index)
    m = df[cols].fillna(False).astype(bool)
    names = [c.removeprefix("__dq_") for c in cols]
    return m.apply(lambda r: ";".join(n for n, v in zip(names, r) if v), axis=1)


def flag_counts(df: pd.DataFrame) -> dict:
    return {c.removeprefix("__dq_"): int(df[c].fillna(False).astype(bool).sum())
            for c in sorted(df.columns) if c.startswith("__dq_") and df[c].fillna(False).astype(bool).any()}
