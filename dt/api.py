"""Single backend facade for the dashboard (P4). Returns DataFrames or contracts/models.py dataclasses only.

    list_datasets()                         -> DataFrame
    inspect_file(paths)                     -> InspectResult
    load_file(paths, mapping, asset, ...)   -> Dataset            (also computes and caches the run)
    get_run(dataset_id)                     -> Run
    state_at(dataset_id, t)                 -> StateAt
    replay(dataset_id, speed, ...)          -> Iterator[StateAt]
    self_test()                             -> DataFrame          (CPRI Excel format)
    snapshot_table(dataset_id)              -> DataFrame          (records ranked worst health first)
    report_pdf(dataset_id)                  -> bytes              (stub: final signature, not built yet)

Runs for N, S1-S5 (S4a/S4b) and Kaggle are precomputed in data/cache/runs/<id>/:
    python -m dt.api rebuild [ID ...]
Uploaded datasets are cached the same way (id "u-..."), so they survive a restart.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import shutil
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from analytics import health as health_mod
from analytics.common import load_thresholds
from analytics.pipeline import analyze, analyze_snapshot
from contracts.canonical import TZ
from contracts.models import (Alert, AnalysisResult, Dataset, Health, InspectResult, Recommendation, RUL, Run,
                              StateAt)
from eval import scenarios as sc
from ingest import adapter
from sim.replay import Replay
from twin.engine import TwinEngine

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "data" / "cache" / "runs"
CACHED = {**{s: f"Transformer-1 · scenario {s} (SIMULATED)" for s in sc.SCENARIOS},
          "kaggle": "Kaggle unit · real field data (different, unrated transformer)"}
TWIN_PREFIXES = ("twin_", "rise_", "aging_", "days_", "residual_", "fidelity_", "hs_", "ageing_", "implausible",
                 "load_pu", "dt_min")
ALERT_WINDOW = pd.Timedelta(hours=24)
_MEM: dict[str, Run] = {}


# ---------------------------------------------------------------- serialisation of the cache
def _jsonable(o):
    if isinstance(o, pd.Timestamp):
        return o.isoformat()
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if math.isnan(float(o)) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, (pd.DataFrame,)):
        return None
    if dataclasses.is_dataclass(o):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(o).items()}
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_jsonable(v) for v in o]
    return o


def _ts(x):
    return None if x is None else pd.Timestamp(x)


def _alert(d: dict) -> Alert:
    return Alert(**{**d, "timestamp": _ts(d["timestamp"])})


def _analysis(d: dict) -> AnalysisResult:
    return AnalysisResult(
        alerts=[_alert(a) for a in d["alerts"]],
        recommendations=[Recommendation(**r) for r in d["recommendations"]],
        health=Health(**d["health"]), rul=RUL(**d["rul"]) if d.get("rul") else None,
        fidelity_rmse_C=d.get("fidelity_rmse_C"))


def _write(run: Run) -> Path:
    d = RUNS / run.dataset_id
    tmp = d.with_suffix(".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for name, df in (("trend", run.trend), ("events", run.events), ("health_series", run.health_series)):
        plain = df.copy()
        plain.attrs = {}  # attrs hold dataclasses (twin summary); they are saved in run.json instead
        plain.to_parquet(tmp / f"{name}.parquet", index=False)
    rep = {k: v for k, v in run.health_report.items() if not isinstance(v, pd.DataFrame)}
    meta = {"dataset_id": run.dataset_id, "name": run.name, "mode": run.mode, "capabilities": run.capabilities,
            "health_report": rep, "asset": run.asset, "summary": run.summary, "analysis": run.analysis,
            "built": pd.Timestamp.now(tz=TZ)}
    (tmp / "run.json").write_text(json.dumps(_jsonable(meta), indent=1, default=str), encoding="utf-8")
    shutil.rmtree(d, ignore_errors=True)
    tmp.rename(d)
    return d


def _read(dataset_id: str) -> Run:
    d = RUNS / dataset_id
    meta = json.loads((d / "run.json").read_text(encoding="utf-8"))
    return Run(dataset_id=meta["dataset_id"], name=meta["name"], mode=meta["mode"],
               trend=pd.read_parquet(d / "trend.parquet"), events=pd.read_parquet(d / "events.parquet"),
               health_series=pd.read_parquet(d / "health_series.parquet"), analysis=_analysis(meta["analysis"]),
               capabilities=meta["capabilities"], health_report=meta["health_report"], asset=meta["asset"],
               summary=meta["summary"])


# ---------------------------------------------------------------- building runs
def _summary(twin: pd.DataFrame) -> dict:
    a = twin.attrs
    keep = ("mode", "plausibility", "rul_display", "life_consumed_days", "drift_message", "first_drift_alert",
            "fidelity_rmse_C_last", "disabled")
    return _jsonable({k: a.get(k) for k in keep if k in a})


def _snapshot_health(table: pd.DataFrame) -> Health:
    worst = table.iloc[0] if len(table) else None
    if worst is None:
        return Health(score=100.0, band="Green", components={}, weights={}, capped=False)
    comps = {k: float(worst[k]) for k in health_mod.SUB_SCORES if k in table and pd.notna(worst[k])}
    return Health(score=float(worst["score"]), band=str(worst["band"]), components=comps, weights={}, capped=False)


def _losses(asset: dict) -> dict:
    """Twin needs losses. Without a nameplate: Transformer-1's loss ratios scaled to the rating. [Assumed]"""
    if asset.get("load_loss_W") and asset.get("no_load_loss_W"):
        return {}
    kva = float(asset.get("rating_kVA") or asset["i_rated_A"] * np.sqrt(3) * asset.get("lv_voltage_V", 415) / 1000)
    return {"load_loss_W": 10.0 * kva, "no_load_loss_W": 1.1 * kva, "losses_source": "assumed: scaled from Transformer-1"}


def _build(dataset_id: str, name: str, ds: Dataset, twin: pd.DataFrame | None = None, caps: dict | None = None,
           asset: dict | None = None, residual_ref: dict | None = None) -> Run:
    asset = dict(asset or {**ds.asset, **_losses(ds.asset)})
    asset.pop("tags", None)
    twin = TwinEngine(asset).run(ds) if twin is None else twin
    caps = caps or sc.effective_caps(ds.capabilities, twin)
    th = load_thresholds(asset=asset)
    if ds.mode == "snapshot":
        table = analyze_snapshot(twin, caps, th)
        res = AnalysisResult(alerts=[], recommendations=[], health=_snapshot_health(table), rul=None, fidelity_rmse_C=None)
        hs = pd.DataFrame()
    else:
        res = analyze(twin, ds.events, caps, th, residual_reference=residual_ref)
        hs = health_mod.compute_series(twin, res.alerts, caps, th)
        res = dataclasses.replace(res, rul=twin.attrs.get("rul"))
    rep = {k: v for k, v in ds.health_report.items() if not isinstance(v, pd.DataFrame)}
    return Run(dataset_id=dataset_id, name=name, mode=ds.mode, trend=twin.reset_index(drop=True), events=ds.events,
               health_series=hs, analysis=res, capabilities=caps, health_report=_jsonable(rep),
               asset=_jsonable(asset), summary=_summary(twin))


def _build_cached(dataset_id: str) -> Run:
    if dataset_id == "kaggle":
        twin, caps = sc.kaggle()
        rep = json.loads((ROOT / "data" / "clean" / "kaggle_health_report.json").read_text(encoding="utf-8"))
        asset = {**rep["asset"], **sc.KAGGLE_LOSSES}
        ds = Dataset(trend=twin, events=pd.DataFrame(), capabilities=rep["capabilities"], mode=rep["mode"],
                     health_report=rep, asset=asset)
        return _build("kaggle", CACHED["kaggle"], ds, twin=twin, caps=caps, asset=asset)
    twin, events = sc.load_scenario(dataset_id)
    ds = Dataset(trend=twin, events=events, capabilities=sc.capabilities(dataset_id), mode=twin.attrs.get("mode", "full"),
                 health_report={"source": "data/generated", "scenario": dataset_id},
                 asset=adapter.enrich.resolve_asset("config/asset.yaml"))
    return _build(dataset_id, CACHED[dataset_id], ds, twin=twin, caps=sc.capabilities(dataset_id),
                  residual_ref=sc.normal_reference(load_thresholds()))


def rebuild(ids=None) -> list[str]:
    """(Re)compute and cache runs. Default: every precomputed dataset."""
    out = []
    for i in ids or CACHED:
        if i not in CACHED:
            raise ValueError(f"unknown cached dataset {i!r}; known: {sorted(CACHED)}")
        _MEM.pop(i, None)
        _write(_build_cached(i))
        out.append(i)
    return out


# ---------------------------------------------------------------- facade
def list_datasets() -> pd.DataFrame:
    """One row per available dataset (cached scenarios, Kaggle, uploads)."""
    rows = []
    ids = list(CACHED) + sorted(p.name for p in RUNS.glob("u-*") if (p / "run.json").exists()) if RUNS.exists() else list(CACHED)
    for i in ids:
        f = RUNS / i / "run.json"
        if f.exists():
            m = json.loads(f.read_text(encoding="utf-8"))
            t = pd.read_parquet(RUNS / i / "trend.parquet", columns=[c for c in ("timestamp", "simulated", "source")
                                                                      if c in _columns(RUNS / i / "trend.parquet")])
            rows.append({"dataset_id": i, "name": m["name"], "mode": m["mode"], "rows": len(t),
                         "start": t["timestamp"].min() if "timestamp" in t else pd.NaT,
                         "end": t["timestamp"].max() if "timestamp" in t else pd.NaT,
                         "simulated": bool(t["simulated"].any()) if "simulated" in t else False,
                         "source": str(t["source"].iloc[0]) if "source" in t and len(t) else "",
                         "health_score": m["analysis"]["health"]["score"], "health_band": m["analysis"]["health"]["band"],
                         "cached": True})
        else:
            rows.append({"dataset_id": i, "name": CACHED.get(i, i), "mode": None, "rows": 0, "start": pd.NaT,
                         "end": pd.NaT, "simulated": i != "kaggle", "source": "", "health_score": None,
                         "health_band": None, "cached": False})
    return pd.DataFrame(rows)


def _columns(path: Path) -> list[str]:
    import pyarrow.parquet as pq
    return pq.read_schema(path).names


def inspect_file(paths) -> InspectResult:
    """Read + auto-map proposal for the Import page. Nothing is committed."""
    return adapter.inspect([str(p) for p in ([paths] if isinstance(paths, (str, Path)) else paths)])


def load_file(paths, mapping: dict | None = None, asset: dict | str | None = "config/asset.yaml",
              name: str | None = None, dataset_id: str | None = None, interval: str | None = None) -> Dataset:
    """Load through the adapter, then compute and cache the run (get_run(dataset_id) afterwards).

    mapping: {source column: {to, unit}} from the Import page (None = auto-map). asset: asset.yaml path, a dict from
    the UI form (rating_kVA, lv_voltage_V, ...), or None to estimate from data. The id is health_report['dataset_id'].
    """
    paths = [str(p) for p in ([paths] if isinstance(paths, (str, Path)) else paths)]
    schema = {"columns": mapping} if mapping else None
    ds = adapter.load(paths, schema=schema, asset=asset, interval=interval)
    if dataset_id is None:
        h = hashlib.sha1("|".join(paths).encode() + str(time.time()).encode()).hexdigest()[:10]
        dataset_id = f"u-{h}"
    if not dataset_id.startswith("u-"):
        raise ValueError("uploaded dataset ids must start with 'u-'")
    ref = sc.normal_reference(load_thresholds()) if ds.asset.get("nameplate_source") == "asset.yaml" \
        and ds.mode in ("full",) else None
    run = _build(dataset_id, name or Path(paths[0]).name, ds, residual_ref=ref)
    _write(run)
    _MEM[dataset_id] = run
    ds.health_report["dataset_id"] = dataset_id
    return ds


def get_run(dataset_id: str) -> Run:
    if dataset_id in _MEM:
        return _MEM[dataset_id]
    if not (RUNS / dataset_id / "run.json").exists():
        if dataset_id in CACHED:
            rebuild([dataset_id])
        else:
            raise KeyError(f"unknown dataset {dataset_id!r}")
    _MEM[dataset_id] = _read(dataset_id)
    return _MEM[dataset_id]


def _split(row: dict) -> tuple[dict, dict]:
    twin = {k: v for k, v in row.items() if k.startswith(TWIN_PREFIXES)}
    meas = {k: v for k, v in row.items() if k not in twin and not k.startswith("gt_")}
    return meas, twin


def _state(run: Run, i: int, weights: dict) -> StateAt:
    row = run.trend.iloc[i].to_dict()
    ts = pd.Timestamp(row["timestamp"])
    meas, twin = _split(row)
    hs = run.health_series
    if len(hs):
        h = hs.iloc[i]
        hl = Health(score=float(h["score"]), band=str(h["band"]),
                    components={k: float(h[k]) for k in health_mod.SUB_SCORES if pd.notna(h[k])},
                    weights=weights, capped=bool(h["capped"]))
    else:
        hl = run.analysis.health
    alerts = [a for a in run.analysis.alerts if ts - ALERT_WINDOW < a.timestamp <= ts]
    return StateAt(timestamp=ts, row=meas, twin=twin, mode=run.mode, health=hl, alerts=alerts,
                   simulated=bool(row.get("simulated", False)))


def state_at(dataset_id: str, t) -> StateAt:
    """State at the last sample at or before t."""
    run = get_run(dataset_id)
    if run.mode == "snapshot":
        raise ValueError("snapshot datasets have no time axis; use snapshot_table()")
    t = pd.Timestamp(t)
    if t.tzinfo is None:
        t = t.tz_localize(TZ)
    ts = run.trend["timestamp"]
    i = int(ts.searchsorted(t, side="right")) - 1
    if i < 0:
        raise ValueError(f"t={t.isoformat()} is before the first sample {ts.iloc[0].isoformat()}")
    return _state(run, i, run.analysis.health.weights)


def replay(dataset_id: str, speed: float | None = 60.0, start=None, end=None, seed: int = 0,
           dropout: float = 0.0, sleep=time.sleep) -> Iterator[StateAt]:
    """Stream the cached run as a live feed (speed = data-seconds per wall-second; None = no waiting).

    Serving the precomputed run is exact: replay -> step() -> StreamAnalyzer equals the batch run (tests)."""
    run = get_run(dataset_id)
    if run.mode == "snapshot":
        raise ValueError("snapshot datasets have no time axis to replay")
    t = run.trend.assign(_i=np.arange(len(run.trend)))
    for row in Replay(t, speed=speed, seed=seed, dropout=dropout, start=start, end=end, sleep=sleep):
        yield _state(run, int(row["_i"]), run.analysis.health.weights)


def self_test() -> pd.DataFrame:
    """Self-test panel in CPRI's Excel format (docs/reference/Draft Data for Condition Monitoring.xlsx).

    Reproduces the sheet's reference-vs-software rows with our arithmetic (diff, %, pass at <= accuracy_pass_pct)
    and checks our own bench comparators: a ramp through the 50 A / 60 C set points must trip at the set point.
    Bench values are used ONLY here, never as operating alarms."""
    import openpyxl
    bench = load_thresholds()["bench"]
    acc = float(bench["accuracy_pass_pct"])
    wb = openpyxl.load_workbook(ROOT / "docs" / "reference" / "Draft Data for Condition Monitoring.xlsx", data_only=True)
    cells = [[c for c in r] for r in wb.worksheets[0].iter_rows(values_only=True)]
    rows = []

    def add(section, item, ref, soft, unit, setting=None):
        diff = soft - ref
        pct = diff / ref * 100 if ref else np.nan
        rows.append({"section": section, "item": item, "unit": unit, "setting": setting, "reference": float(ref),
                     "software": float(soft), "diff": round(diff, 4), "diff_pct": round(pct, 4),
                     "pass": bool(abs(pct) <= acc)})

    section = None
    for r in cells:
        vals = [v for v in r if v is not None]
        if not vals:
            continue
        head = str(vals[0])
        if head.startswith("Measurement of Voltage"):
            section = "measurement"
        elif head.startswith("Current trip test (Current"):
            section = "current_trip"
        elif head.startswith("Tripping for more temperatures"):
            section = "temperature_trip"
        elif section == "measurement" and head.startswith("CHANNEL") and len(vals) >= 4:
            unit = "A" if "(A)" in str(vals[1]) else "V"
            add("measurement", f"{vals[0]} {str(vals[1]).split()[0]}", vals[2], vals[3], unit)
        elif section == "current_trip" and head in ("R", "Y", "B") and len(vals) >= 3:
            add("current_trip", f"phase {head}", vals[1], vals[2], "A", setting=float(bench["overcurrent_trip_a"]))
        elif section == "temperature_trip" and isinstance(vals[0], (int, float)) and len(vals) >= 4:
            add("temperature_trip", f"test {vals[0]}", vals[2], vals[3], "C", setting=float(vals[1]))
    for item, setp, unit in (("overcurrent comparator", float(bench["overcurrent_trip_a"]), "A"),
                             ("temperature comparator", float(bench["temperature_trip_c"]), "C")):
        ramp = np.round(np.arange(setp - 5, setp + 5, 0.01), 2)
        tripped = float(ramp[np.argmax(ramp >= setp)])
        add("software_trip_check", item, setp, tripped, unit, setting=setp)
    return pd.DataFrame(rows)


def snapshot_table(dataset_id: str) -> pd.DataFrame:
    """Records ranked worst health first. Snapshot datasets: every record. Time series: one operating point per
    day (the highest-load sample), so the worst days come first."""
    run = get_run(dataset_id)
    th = load_thresholds(asset=run.asset)
    t = run.trend
    if run.mode != "snapshot":
        if "load_pu" not in t or t["load_pu"].isna().all():
            return analyze_snapshot(t.iloc[0:0].assign(record_id=[]), run.capabilities, th)
        day = t["timestamp"].dt.strftime("%Y-%m-%d")
        idx = t.assign(_d=day).dropna(subset=["load_pu"]).groupby("_d")["load_pu"].idxmax()
        t = t.loc[idx.values].assign(record_id=lambda d: d["timestamp"].dt.strftime("%Y-%m-%d %H:%M"))
        t = t.drop(columns=["timestamp"])
    return analyze_snapshot(t, run.capabilities, th)


def report_pdf(dataset_id: str) -> bytes:
    """PDF summary incl. Data Health appendix (PRD §10 Reports). STUB: final signature, not built yet (P4)."""
    get_run(dataset_id)  # unknown ids still fail like every other call
    raise NotImplementedError("report_pdf is not built yet (P4: PDF library not chosen)")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "rebuild":
        for i in rebuild(sys.argv[2:] or None):
            print("built", RUNS / i)
    else:
        print("usage: python -m dt.api rebuild [ID ...]   ids:", " ".join(CACHED))
