"""Single backend facade for the dashboard (P4). Returns DataFrames or contracts/models.py dataclasses only.

    list_datasets()                         -> DataFrame
    inspect_file(paths)                     -> InspectResult
    load_file(paths, mapping, asset, ...)   -> Dataset            (also computes and caches the run)
    get_run(dataset_id)                     -> Run
    state_at(dataset_id, t)                 -> StateAt
    replay(dataset_id, speed, ...)          -> Iterator[StateAt]
    self_test()                             -> DataFrame          (CPRI Excel format)
    frames(dataset_id, fields, start, end)  -> DataFrame          (full-resolution aligned columns for replay)
    thermal_profile(dataset_id, t)          -> dict               (IEC 60076-7 thermal diagram + heat flow at t)
    components(dataset_id, t)               -> dict               (per-part quantities, live equations, findings)
    whatif(load_pu, ambient_C, cooling, ...) -> dict              (steady state + approach curve; Simulate mode)
    findings(dataset_id, t)                 -> dict               (findings on parts by CPRI cause; Diagnose mode)
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
from dt import components as comp_mod
from eval import scenarios as sc
from ingest import adapter
from sim.replay import Replay
from twin import profile as profile_mod
from twin.engine import TwinEngine, load_config as twin_config

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "data" / "cache" / "runs"
CACHED = {**{s: f"Transformer-1 · scenario {s} (SIMULATED)" for s in sc.SCENARIOS},
          "kaggle": "Kaggle unit · real field data (different, unrated transformer)"}
TWIN_PREFIXES = ("twin_", "rise_", "aging_", "days_", "residual_", "fidelity_", "hs_", "ageing_", "implausible",
                 "load_pu", "dt_min")
ALERT_WINDOW = pd.Timedelta(hours=24)
_MEM: dict[str, Run] = {}
_PROFILE: dict[int, pd.DataFrame] = {}


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


def frames(dataset_id: str, fields: list[str] | None = None, start=None, end=None, every: int = 1) -> pd.DataFrame:
    """Full-resolution, time-aligned columns for replay and charts: measured + twin columns of the run, the thermal
    profile columns (twin/profile.py COLUMNS), plus the Health Index series as health_score, health_band,
    health_<sub-score>, health_capped. Not downsampled.

    fields: column subset (timestamp is always included); unknown names raise ValueError. every: keep every n-th row.
    """
    run = get_run(dataset_id)
    if run.mode == "snapshot":
        raise ValueError("snapshot datasets have no time axis; use snapshot_table()")
    df = pd.concat([run.trend.reset_index(drop=True), _profile(run).reset_index(drop=True)], axis=1)
    if len(run.health_series):
        hs = run.health_series.drop(columns=["timestamp"]).add_prefix("health_")
        df = pd.concat([df, hs.reset_index(drop=True)], axis=1)
    if fields:
        unknown = sorted(set(fields) - set(df.columns))
        if unknown:
            raise ValueError(f"unknown field(s) {unknown}; available: {sorted(df.columns)}")
        df = df[["timestamp"] + [f for f in fields if f != "timestamp"]]
    for bound, op in ((start, "ge"), (end, "le")):
        if bound is not None:
            b = pd.Timestamp(bound)
            b = b.tz_localize(TZ) if b.tzinfo is None else b
            df = df[getattr(df["timestamp"], op)(b)]
    if every < 1:
        raise ValueError("every must be >= 1")
    return df.iloc[::every].reset_index(drop=True)


def _profile(run: Run) -> pd.DataFrame:
    key = id(run)
    if key not in _PROFILE:
        _PROFILE[key] = profile_mod.compute(run.trend, run.asset, float(twin_config()["bottom_oil_ratio"]))
    return _PROFILE[key]


def _params(run: Run) -> dict:
    return profile_mod.params(profile_mod.specs_for(run.asset), float(twin_config()["bottom_oil_ratio"]))


def _index_at(run: Run, t) -> int:
    if run.mode == "snapshot":
        raise ValueError("snapshot datasets have no time axis; use snapshot_table()")
    t = pd.Timestamp(t)
    if t.tzinfo is None:
        t = t.tz_localize(TZ)
    ts = run.trend["timestamp"]
    i = int(ts.searchsorted(t, side="right")) - 1
    if i < 0:
        raise ValueError(f"t={t.isoformat()} is before the first sample {ts.iloc[0].isoformat()}")
    return i


def _val(v, unit: str, estimated: bool, source: str) -> dict:
    try:
        f = float(v)
    except (TypeError, ValueError):
        f = math.nan
    return {"value": f if math.isfinite(f) else None, "unit": unit, "estimated": estimated, "source": source}


def thermal_profile(dataset_id: str, t) -> dict:
    """IEC 60076-7 thermal diagram and heat flow at the last sample at or before t (twin/profile.py).

    values: name -> {value, unit, estimated, source}; source: measured | twin | model (a constant of the model).
    Measured-based values are None in meter_only mode or where measured OTI does not drive ageing (untrusted)."""
    run = get_run(dataset_id)
    i = _index_at(run, t)
    row, pr = run.trend.iloc[i], _profile(run).iloc[i]
    meas_ok = run.mode != "meter_only" and row.get("ageing_source") == "measured"
    U = profile_mod.COLUMNS
    vals = {
        "load_pu": _val(row.get("load_pu"), "pu", False, "measured"),
        "ambient_C": _val(row.get("amb_C"), "°C", False, "measured"),
        "bottom_oil_C": _val(pr["bottom_oil_C"], "°C", True, "twin"),
        "top_oil_C": _val(row.get("twin_oil_C"), "°C", False, "twin"),
        "top_oil_measured_C": _val(row.get("OTI_C") if meas_ok else None, "°C", False, "measured"),
        "avg_winding_C": _val(pr["avg_winding_C"], "°C", True, "twin"),
        "hot_spot_C": _val(row.get("twin_hs_C"), "°C", False, "twin"),
        "hot_spot_measured_C": _val(row.get("hs_ageing_C") if meas_ok else None, "°C", False, "measured"),
        "winding_gradient_K": _val(pr["hs_gradient_K"], "K", False, "twin"),
        "hot_spot_factor": _val(pr["hot_spot_factor"], "", False, "model"),
        "top_oil_ss_C": _val(pr["top_oil_ss_C"], "°C", False, "twin"),
        "hot_spot_ss_C": _val(pr["hot_spot_ss_C"], "°C", False, "twin"),
        "ageing_rate": _val(row.get("aging_rate"), "× normal", False, "twin"),
        "ageing_rate_actual": _val(row.get("aging_rate_actual"), "× normal", False, "measured" if meas_ok else "twin"),
        "life_used_days": _val(row.get("days_aged_cum"), "days", False, "twin"),
        "life_used_actual_days": _val(row.get("days_aged_actual_cum"), "days", False, "measured" if meas_ok else "twin"),
    }
    for c in ("losses_noload_W", "losses_load_W", "losses_total_W", "heat_dissipated_W", "heat_stored_W",
              "oil_flow_intensity", "radiator_effectiveness", "tau_oil_min", "tau_winding_min"):
        vals[c] = _val(pr[c], U[c][0], U[c][1], "model" if c.startswith("tau") else "twin")
    return {"dataset_id": dataset_id, "timestamp": row["timestamp"], "mode": run.mode, "values": vals,
            "params": _params(run), "simulated": bool(row.get("simulated", False))}


def components(dataset_id: str, t) -> dict:
    """Per-part quantities, governing equations with live values, active findings and tests at t (dt/components.py)."""
    run = get_run(dataset_id)
    i = _index_at(run, t)
    row = run.trend.iloc[i].to_dict()
    ts = pd.Timestamp(row["timestamp"])
    alerts = [a for a in run.analysis.alerts if ts - ALERT_WINDOW < a.timestamp <= ts]
    oti_suspect = (run.summary.get("plausibility") or {}).get("OTI_C") == "suspect"
    parts = comp_mod.build(row, _profile(run).iloc[i].to_dict(), _params(run), run.asset, run.mode, alerts,
                           run.analysis.recommendations, oti_suspect=oti_suspect)
    return {"dataset_id": dataset_id, "timestamp": ts, "mode": run.mode, "parts": parts,
            "simulated": bool(row.get("simulated", False))}


CAUSES = {  # alert module -> CPRI cause group (the three causes first), in display order
    "overloading": "Overloading", "insulation": "Insulation", "short_circuit": "Short circuit",
    "electrical": "Supply and connections", "oil": "Oil", "moisture": "Oil", "data": "Sensors and data"}


def whatif(load_pu: float, ambient_C: float, cooling: float = 1.0, dataset_id: str | None = None, t=None) -> dict:
    """Steady state of the twin at a load, ambient and cooling effectiveness (twin/profile.py whatif).

    With dataset_id: that dataset's asset (rating, losses). With dataset_id and t: the approach starts from the
    twin's state at t (top-oil and winding gradient), else from cold (ambient)."""
    if not 0 <= load_pu <= 2:
        raise ValueError("load_pu must be within 0-2")
    if not -10 <= ambient_C <= 60:
        raise ValueError("ambient_C must be within -10..60")
    if not 0.05 <= cooling <= 1.5:
        raise ValueError("cooling must be within 0.05-1.5 (1 = radiators as designed)")
    start_top = start_grad = None
    if dataset_id is not None:
        run = get_run(dataset_id)
        p = _params(run)
        if t is not None and run.mode != "snapshot":
            row = run.trend.iloc[_index_at(run, t)]
            if pd.notna(row.get("twin_oil_C")) and pd.notna(row.get("twin_hs_C")):
                start_top, start_grad = float(row["twin_oil_C"]), float(row["twin_hs_C"] - row["twin_oil_C"])
    else:
        a = adapter.enrich.resolve_asset("config/asset.yaml")
        p = profile_mod.params(profile_mod.specs_for(a), float(twin_config()["bottom_oil_ratio"]))
    out = profile_mod.whatif(p, float(load_pu), float(ambient_C), float(cooling), start_top, start_grad)
    out["params"] = p
    out["estimated"] = sorted(k for k, (_, est) in profile_mod.COLUMNS.items() if est)
    return out


def findings(dataset_id: str, t=None) -> dict:
    """Findings up to t (default: the whole run), one per alert type and part set (the latest, with a count),
    grouped by CPRI cause, each with the parts it is drawn on and its recommendation; plus the through-fault
    stress state (cumulative I2t, qualifying events vs the %X-test rule)."""
    from analytics import through_fault
    run = get_run(dataset_id)
    ts_end = None
    if t is not None:
        ts_end = pd.Timestamp(t)
        ts_end = ts_end.tz_localize(TZ) if ts_end.tzinfo is None else ts_end
    alerts = [a for a in run.analysis.alerts if ts_end is None or a.timestamp <= ts_end]
    recs = {r.alert_id: r for r in run.analysis.recommendations}
    groups: dict[tuple, dict] = {}
    for a in sorted(alerts, key=lambda a: a.timestamp):
        parts = comp_mod.parts_for_alert(a)
        key = (a.type, a.origin, parts)
        g = groups.setdefault(key, {"type": a.type, "origin": a.origin, "parts": list(parts), "count": 0,
                                    "first": a.timestamp, "cause": CAUSES.get(a.module, a.module)})
        r = recs.get(a.id)
        g.update(count=g["count"] + 1, id=a.id, last=a.timestamp, severity=a.severity, explanation=a.explanation,
                 module=a.module, indicative=a.severity == "info",
                 recommendation=None if r is None else {"action": r.action, "test": r.test, "urgency": r.urgency,
                                                         "standard_ref": r.standard_ref})
    order = list(dict.fromkeys(CAUSES.values()))
    sev = {"critical": 0, "warning": 1, "info": 2}
    items = sorted(groups.values(), key=lambda g: (order.index(g["cause"]) if g["cause"] in order else 99,
                                                   g["origin"] == "sensor", sev.get(g["severity"], 3), g["last"]))
    th = load_thresholds(asset=run.asset)["operating"]["through_fault"]
    ev = run.events
    if len(ev) and ts_end is not None:
        ev = ev[pd.to_datetime(ev["timestamp"]) <= ts_end]
    st = through_fault.stress_table(ev, load_thresholds(asset=run.asset)) if len(ev) else pd.DataFrame()
    last = st.iloc[-1] if len(st) else None
    stress = {"events": int(len(st)), "moderate_pu": th["moderate_pu"], "severe_pu": th["severe_pu"],
              "moderate_limit": int(th["moderate_count"]),
              "qualifying": 0 if last is None else int(last["moderate_count_since_reset"]),
              "severe_seen": bool(len(st) and (st["severity_class"] == "severe").any()),
              "triggered": bool(last is not None and last["triggered"]),
              "cum_i2t_pu2s": 0.0 if last is None else float(last["cum_i2t_pu2s"]),
              "last_event": None if last is None else {"timestamp": last["timestamp"], "peak_pu": float(last["peak_pu"]),
                                                       "duration_ms": float(last["duration_ms"]),
                                                       "class": str(last["severity_class"])}}
    return {"dataset_id": dataset_id, "timestamp": ts_end, "causes": order, "findings": items, "stress": stress,
            "simulated": bool(run.trend["simulated"].any()) if "simulated" in run.trend else False}


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
