"""Step 2 SHAPE (Tier 1): table roles, multi-file merge on time, event-table canonicalisation."""
import numpy as np
import pandas as pd

from contracts.canonical import EVENT_COLUMNS, empty_events
from ingest.map import normalize
from ingest.time import find_time_column, parse
from ingest.units import header_hint

NAMEPLATE_KEYS = ("kva", "rating", "impedance", "loss", "vector", "nameplate")
EVENT_KEYS = ("event", "peak", "duration")


def classify(df: pd.DataFrame) -> str:
    norms = [normalize(c) for c in df.columns]
    first = df.iloc[:, 0].astype(str).str.lower() if df.shape[1] else pd.Series(dtype=str)
    if len(df) <= 40 and first.str.contains("|".join(NAMEPLATE_KEYS)).sum() >= 2:
        return "nameplate"
    tcol = find_time_column(df)
    if tcol is not None and any(k in n for n in norms for k in EVENT_KEYS):
        return "events"
    if tcol is not None and df.select_dtypes("number").shape[1] >= 1:
        return "trend"
    return "other"


def merge(frames: list[pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    """Outer join on timestamp. Same canonical column in two files: first wins, MERGE_CONFLICT where they differ."""
    out = frames[0].copy()
    out["__in_1"] = True
    stats = {"tables": len(frames), "rows_per_table": [len(f) for f in frames]}
    for i, f in enumerate(frames[1:], start=2):
        f = f.copy()
        f[f"__in_{i}"] = True
        shared = [c for c in f.columns if c in out.columns and c != "timestamp"]
        out = out.merge(f, on="timestamp", how="outer", suffixes=("", "__r"))
        for c in shared:
            r = out.pop(c + "__r")
            if c.startswith("__dq_"):
                out[c] = out[c].fillna(False).astype(bool) | r.fillna(False).astype(bool)
                continue
            both = out[c].notna() & r.notna()
            conflict = both & (out[c] != r)
            if pd.api.types.is_numeric_dtype(out[c]):
                conflict &= ~np.isclose(out[c].fillna(0), r.fillna(0), rtol=1e-3)
            out["__dq_MERGE_CONFLICT"] = out.get("__dq_MERGE_CONFLICT", False) | conflict
            out[c] = out[c].combine_first(r)
    if len(frames) > 1:
        present = [out.get(f"__in_{i}", pd.Series(True, index=out.index)).fillna(False).astype(bool)
                   for i in range(1, len(frames) + 1)]
        stats["rows_after_merge"] = len(out)
        stats["rows_in_all_tables"] = int(pd.concat(present, axis=1).all(axis=1).sum()) if present else len(out)
    out = out.drop(columns=[c for c in out.columns if c.startswith("__in_")])
    out = out.sort_values("timestamp").reset_index(drop=True)
    for c in out.columns:
        if c.startswith("__dq_"):
            out[c] = out[c].fillna(False).astype(bool)
    return out, stats


def to_events(df: pd.DataFrame, i_rated: float | None, source: str, simulated: bool) -> pd.DataFrame:
    if df is None or df.empty:
        return empty_events()
    cols = {normalize(c): c for c in df.columns}
    tcol = find_time_column(df)
    ts, _ = parse(df[tcol])
    ev = pd.DataFrame({"timestamp": ts})
    typ = next((cols[k] for k in ("event_type", "event", "type", "fault_type", "fault") if k in cols), None)
    raw_type = df[typ].astype(str).str.lower() if typ else pd.Series("other", index=df.index)
    ev["event_type"] = np.select(
        [raw_type.str.contains("through|short|fault"), raw_type.str.contains("trip"),
         raw_type.str.contains("tamper|theft"), raw_type.str.contains("alarm")],
        ["through_fault", "trip", "tamper", "alarm"], "other")
    ph = next((cols[k] for k in ("phase", "ph") if k in cols), None)
    ev["phase"] = df[ph].astype(str).str.upper().replace({"A": "R", "C": "B", "ALL": "3ph", "3PH": "3ph"}) if ph else "unknown"
    if "peak_pu" in cols:
        ev["peak_pu"] = pd.to_numeric(df[cols["peak_pu"]], errors="coerce")
    else:
        pk = next((c for n, c in cols.items() if "peak" in n), None)
        if pk is not None and i_rated:
            amps = pd.to_numeric(df[pk], errors="coerce") * (1000 if header_hint(pk) == "kA" else 1)
            ev["peak_pu"] = amps / i_rated
        else:
            ev["peak_pu"] = np.nan
    dur = next((c for n, c in cols.items() if "duration" in n), None)
    if dur is not None:
        d = pd.to_numeric(df[dur], errors="coerce")
        is_s = normalize(dur).endswith("_s") or "(s)" in str(dur).lower() or "sec" in str(dur).lower()
        ev["duration_ms"] = d * 1000 if is_s else d
    else:
        ev["duration_ms"] = np.nan
    ev["i2t_pu2s"] = ev["peak_pu"] ** 2 * ev["duration_ms"] / 1000
    ev["source"], ev["simulated"] = source, simulated
    return ev[EVENT_COLUMNS].sort_values("timestamp").reset_index(drop=True)
