"""Step 3 TIME: find, parse (day-first default), tz, dedupe, interval."""
import numpy as np
import pandas as pd

from contracts.canonical import TZ

TIME_NAMES = ("timestamp", "devicetimestamp", "datetime", "date_time", "time_stamp", "eventtime", "ts", "time", "date")


def norm(h) -> str:
    return "".join(ch for ch in str(h).lower() if ch.isalnum() or ch == "_").replace("__", "_")


def find_time_column(df: pd.DataFrame) -> str | tuple[str, str] | None:
    names = {norm(c): c for c in df.columns}
    if "date" in names and "time" in names:
        return (names["date"], names["time"])
    for n in TIME_NAMES:
        if n in names:
            return names[n]
    for c in df.columns:  # by parse success
        if pd.api.types.is_string_dtype(df[c]) and pd.to_datetime(df[c].head(50), errors="coerce", format="mixed",
                                                    dayfirst=True).notna().mean() > 0.9:
            return c
    return None


def parse(s: pd.Series, dayfirst: bool | None = None) -> tuple[pd.Series, dict]:
    """Parse to tz-aware Asia/Kolkata. dayfirst=None: ISO, then day-first, then month-first."""
    info = {}
    if pd.api.types.is_datetime64_any_dtype(s):
        ts, info["format"] = pd.to_datetime(s), "datetime"
    elif pd.api.types.is_numeric_dtype(s):
        med = float(np.nanmedian(s.astype(float)))
        if med > 1e11:
            ts, info["format"] = pd.to_datetime(s, unit="ms", utc=True), "epoch_ms"
        elif med > 1e9:
            ts, info["format"] = pd.to_datetime(s, unit="s", utc=True), "epoch_s"
        else:
            ts, info["format"] = pd.to_datetime(s, unit="D", origin="1899-12-30"), "excel_serial"
    else:
        s = s.astype(str).str.strip()
        tries = []
        if dayfirst is None:
            tries.append(("iso8601", dict(format="ISO8601")))
            tries += [("day_first", dict(format="mixed", dayfirst=True)), ("month_first", dict(format="mixed", dayfirst=False))]
        else:
            tries.append(("day_first" if dayfirst else "month_first", dict(format="mixed", dayfirst=dayfirst)))
        ts = None
        for name, kw in tries:
            cand = pd.to_datetime(s, errors="coerce", **kw)
            if cand.notna().mean() >= 0.95:
                ts, info["format"] = cand, name
                break
        if ts is None:
            ts, info["format"] = pd.to_datetime(s, errors="coerce", format="mixed", dayfirst=True), "day_first_partial"
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(TZ, ambiguous="NaT", nonexistent="NaT")
        info["tz"] = f"assumed {TZ}"
    else:
        ts = ts.dt.tz_convert(TZ)
        info["tz"] = "converted"
    info["parsed_ok_pct"] = round(100 * ts.notna().mean(), 2)
    return ts, info


def dedupe(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Identical rows at a timestamp -> keep one (DUP_IDENT). Conflicting -> median (alarm_*: max), DUP_CONFLICT."""
    data_cols = [c for c in df.columns if c != "timestamp" and not c.startswith("__dq_")]
    n = df.groupby("timestamp").size()
    dup_ts = n.index[n > 1]
    distinct = df.drop_duplicates(subset=["timestamp", *data_cols]).groupby("timestamp").size()
    conflict_ts = distinct.index[distinct > 1]
    stats = {"rows_in": len(df), "dup_groups": len(dup_ts), "dup_rows": int(n[n > 1].sum()),
             "conflict_groups": len(conflict_ts), "identical_groups": len(dup_ts) - len(conflict_ts)}
    if len(dup_ts) == 0:
        return df.sort_values("timestamp").reset_index(drop=True), stats
    agg = {}
    for c in df.columns:
        if c == "timestamp":
            continue
        if c.startswith(("__dq_", "alarm_")):
            agg[c] = "max"
        elif pd.api.types.is_numeric_dtype(df[c]):
            agg[c] = "median"
        else:
            agg[c] = "first"
    out = df.groupby("timestamp", sort=True).agg(agg).reset_index()
    out["__dq_DUP_IDENT"] = out["timestamp"].isin(dup_ts.difference(conflict_ts))
    out["__dq_DUP_CONFLICT"] = out["timestamp"].isin(conflict_ts)
    stats["rows_out"] = len(out)
    return out, stats


def interval(ts: pd.Series) -> pd.Timedelta:
    d = ts.sort_values().diff().dropna()
    d = d[d > pd.Timedelta(0)]
    return d.median() if len(d) else pd.Timedelta("15min")
