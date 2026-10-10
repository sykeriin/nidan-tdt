"""Universal adapter, Tier 1 (DATA_INGESTION_SPEC.md). Any CSV/Excel -> canonical Dataset.

    python -m ingest.adapter inspect FILE [FILE ...]
    python -m ingest.adapter load FILE [FILE ...] [--schema config/schema/x.yaml] [--save-schema PATH]

Files, replay and live sensors share one mapping path; map_row() is the per-row version.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from contracts.canonical import EVENT_COLUMNS, TREND_COLUMNS, empty_events
from contracts.models import Dataset, InspectResult
from ingest import capabilities, derive, enrich, map as cmap, shape, time as ctime, validate
from ingest.read import read

ROOT = Path(__file__).resolve().parent.parent


def _load_schema(schema) -> dict | None:
    if schema is None or isinstance(schema, dict):
        return schema
    p = Path(schema)
    return yaml.safe_load((p if p.is_absolute() or p.exists() else ROOT / p).read_text(encoding="utf-8"))


def _tables(paths) -> list[tuple[str, pd.DataFrame, dict, str]]:
    out = []
    for p in paths:
        for name, df, info in read(p):
            out.append((name, df, info, shape.classify(df)))
    return out


def _time(df: pd.DataFrame, ts_spec: dict) -> tuple[pd.DataFrame, dict]:
    col = ts_spec.get("column") or ctime.find_time_column(df)
    if col is None:
        raise ValueError(f"no timestamp column found.{_records_hint([df])} Set schema timestamp.column if one exists.")
    if isinstance(col, (list, tuple)):
        raw = df[col[0]].astype(str) + " " + df[col[1]].astype(str)
        rest = df.drop(columns=list(col))
    else:
        raw, rest = df[col], df.drop(columns=[col])
    ts, info = ctime.parse(raw, ts_spec.get("dayfirst"))
    info["column"] = col
    out = rest.copy()
    out.insert(0, "timestamp", ts)
    bad = out["timestamp"].isna()
    info["unparsed_rows"] = int(bad.sum())
    return out[~bad].reset_index(drop=True), info


def _records_hint(frames) -> str:
    """Tables keyed by a record ID with no time column (CPRI screening style) get a specific message."""
    for df in frames:
        ids = [c for c in df.columns if str(c).lower().endswith(("_id", "id"))]
        if ids:
            return (f" It looks like per-test records keyed by {str(ids[0])!r} (CPRI screening-workbook style);"
                    " the twin needs a time series.")
    return ""


def _split_existing_flags(df: pd.DataFrame) -> pd.DataFrame:
    """A canonical file already carrying dq_flags keeps them."""
    if "dq_flags" not in df:
        return df
    codes = df.pop("dq_flags").fillna("").astype(str)
    for code in sorted({c for s in codes for c in s.split(";") if c}):
        df[f"__dq_{code}"] = codes.str.split(";").apply(lambda xs, k=code: k in xs)
    return df


def inspect(paths, synonyms=None) -> InspectResult:
    tables = _tables(paths)
    trend = [(n, d) for n, d, _, r in tables if r == "trend"]
    if not trend:
        raise ValueError("no trend table found")
    name, df = trend[0]
    col = ctime.find_time_column(df)
    timed, tinfo = _time(df, {})
    proposals = []
    for n, d in trend:
        t, _ = _time(d, {})
        proposals += cmap.propose(t, synonyms)
    return InspectResult(
        tables=[{"name": n, "role": r, "rows": len(d), "columns": [str(c) for c in d.columns]} for n, d, _, r in tables],
        timestamp={"column": col, "format": tinfo.get("format"), "parsed_ok_pct": tinfo["parsed_ok_pct"]},
        proposals=proposals, preview=timed.head(10))


def load(paths, schema=None, asset="config/asset.yaml", source: str | None = None,
         simulated: bool | None = None, start=None, end=None, weather: pd.DataFrame | None = None) -> Dataset:
    """Full pipeline. schema=None -> auto-map (confidence >= 0.6). asset: yaml path | dict | None (estimate)."""
    paths = [paths] if isinstance(paths, (str, Path)) else list(paths)
    sch = _load_schema(schema) or {}
    rep = {"files": [str(p) for p in paths], "warnings": []}
    tables = _tables(paths)
    rep["tables"] = [{"name": n, "role": r, "rows_read": len(d), **info} for n, d, info, r in tables]
    source = source or sch.get("source") or "organizer"
    simulated = sch.get("simulated", False) if simulated is None else simulated
    if "asset" in sch:
        asset = sch["asset"]
    a = enrich.resolve_asset(asset)

    # per trend table: time -> map/units -> dedupe
    frames, mapping, conversions, dropped, dedupe_stats = [], [], [], [], {}
    for name, df, _, role in tables:
        if role != "trend":
            continue
        df, tinfo = _time(df, sch.get("timestamp", {}))
        rep.setdefault("time", {})[name] = tinfo
        if "columns" in sch:
            cols = sch["columns"]
            mapping += [{"table": name, "source": str(k), "canonical": v.get("to"), "unit": v.get("unit", "-"),
                         "confidence": "schema"} for k, v in cols.items() if k in df.columns]
        else:
            props = cmap.propose(df)
            cols = cmap.schema_from_proposals(props)
            mapping += [{"table": name, **{k: p[k] for k in ("source", "canonical", "proposed", "confidence", "unit")}}
                        for p in props]
        m, drop, conv = cmap.apply(df, cols)
        m = _split_existing_flags(m)
        dropped += [f"{name}:{d}" for d in drop]
        conversions += conv
        m, st = ctime.dedupe(m)
        dedupe_stats[name] = st
        frames.append(m)
    if not frames:
        raise ValueError("no trend table found." + _records_hint([d for _, d, _, _ in tables]))
    trend, merge_stats = shape.merge(frames)
    rep["dedupe"], rep["merge"] = dedupe_stats, merge_stats
    rng = sch.get("range", {})
    start, end = start or rng.get("start"), end or rng.get("end")
    if start is not None:
        trend = trend[trend["timestamp"] >= pd.Timestamp(start, tz="Asia/Kolkata")]
    if end is not None:
        trend = trend[trend["timestamp"] <= pd.Timestamp(end, tz="Asia/Kolkata")]
    trend = trend.reset_index(drop=True)
    if trend.empty:
        raise ValueError("no rows after time parsing / range filter")
    iv = ctime.interval(trend["timestamp"])
    rep["interval"] = str(iv)
    if iv > pd.Timedelta("60min"):
        rep["warnings"].append("coarse data (> 60 min): thermal dynamics under-resolved")
    if iv < pd.Timedelta("1min"):
        rep["warnings"].append("sub-minute data: Tier 1 does not resample; expect noisy jump flags")

    # derive -> nameplate -> validate -> enrich -> loading
    trend, derive_log = derive.derive(trend, a)
    if not a.get("i_rated_A"):
        a = enrich.resolve_asset(None if a.get("nameplate_source") == "estimated" else a, trend)
        if a.get("nameplate_source") == "estimated":
            rep["warnings"].append(f"Rating unknown: estimated I_rated {a.get('i_rated_A')} A "
                                   f"({a.get('rating_kVA')} kVA) from data [Assumed - estimated from data]")
    trend = validate.validate(trend, iv, a.get("i_rated_A"))
    wx = enrich.load_weather(site=sch.get("site", enrich.DEFAULT_SITE)) if weather is None else weather
    rep["weather_site"] = sch.get("site", enrich.DEFAULT_SITE)
    trend, enrich_log = enrich.fill_ambient(trend, wx)
    trend["__dq_ATI_MISMATCH"] = enrich.ati_mismatch(trend, wx)
    trend = derive.add_loading(trend, a.get("i_rated_A"))

    # finalise
    trend["dq_flags"] = validate.flags_to_string(trend)
    flag_counts = validate.flag_counts(trend)
    if "source" not in trend or trend["source"].isna().all():
        trend["source"] = source
    if "simulated" not in trend or trend["simulated"].isna().all():
        trend["simulated"] = simulated
    trend["simulated"] = trend["simulated"].astype(str).str.lower().isin(["true", "1"])
    order = [c for c in TREND_COLUMNS if c in trend]
    extras = sorted(c for c in trend if c.startswith(("alarm_", "gt_", "extra_")))
    trend = trend[order + extras]

    ev_tables = [d for _, d, _, r in tables if r == "events"]
    events = pd.concat([shape.to_events(d, a.get("i_rated_A"), source, simulated) for d in ev_tables],
                       ignore_index=True) if ev_tables else empty_events()
    caps, mode = capabilities.compute(trend, events)
    rep.update({
        "rows_after_cleaning": len(trend), "time_span": [str(trend["timestamp"].min()), str(trend["timestamp"].max())],
        "mapping": mapping, "unit_conversions": conversions, "derived": derive_log, "enrichment": enrich_log,
        "dropped_columns": dropped, "flag_counts": flag_counts, "capabilities": caps, "mode": mode,
        "nameplate_source": a.get("nameplate_source"), "events": len(events),
    })
    return Dataset(trend=trend, events=events, capabilities=caps, mode=mode, health_report=rep, asset=a)


def map_row(raw: dict, schema: dict, asset: dict, weather: pd.DataFrame | None = None) -> dict:
    """Same map/units/derive/enrich for one streaming row. Window checks (dedupe, jumps, stuck) are batch-only."""
    df = pd.DataFrame([raw])
    df, _ = _time(df, schema.get("timestamp", {}))
    m, _, _ = cmap.apply(df, schema["columns"])
    m = _split_existing_flags(m)
    a = enrich.resolve_asset(asset)
    m, _ = derive.derive(m, a)
    m = validate.validate(m, pd.Timedelta("15min"), a.get("i_rated_A"))
    m, _ = enrich.fill_ambient(m, enrich.load_weather() if weather is None else weather)
    m = derive.add_loading(m, a.get("i_rated_A"))
    m["dq_flags"] = validate.flags_to_string(m)
    row = {k: v for k, v in m.iloc[0].items() if not k.startswith("__dq_")}
    row.setdefault("source", schema.get("source", "live"))
    row.setdefault("simulated", schema.get("simulated", False))
    return row


def save_schema(ds_or_proposals, path, name: str, timestamp: dict | None = None, **extra) -> Path:
    props = ds_or_proposals.health_report["mapping"] if isinstance(ds_or_proposals, Dataset) else ds_or_proposals
    cols = {p["source"]: {"to": p["canonical"], "unit": p["unit"]} for p in props if p.get("canonical")}
    doc = {"name": name, **extra, "timestamp": timestamp or {}, "columns": cols}
    Path(path).write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return Path(path)


def _jsonable(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    return str(o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["inspect", "load"])
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--schema")
    ap.add_argument("--save-schema")
    a = ap.parse_args()
    if a.cmd == "inspect":
        r = inspect(a.paths)
        print(json.dumps({"tables": r.tables, "timestamp": r.timestamp}, indent=1, default=_jsonable))
        for p in r.proposals:
            print(f"  {str(p['source']):<28} -> {str(p['canonical']):<14} conf {p['confidence']:<5} unit {p['unit']}")
        print(r.preview.to_string())
    else:
        ds = load(a.paths, schema=a.schema)
        h = {k: v for k, v in ds.health_report.items() if k != "mapping"}
        print(json.dumps(h, indent=1, default=_jsonable))
        if a.save_schema:
            print("saved", save_schema(ds, a.save_schema, Path(a.save_schema).stem))


if __name__ == "__main__":
    main()
