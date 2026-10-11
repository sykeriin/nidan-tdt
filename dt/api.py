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
from twin import physics, profile
from twin import thermal_profile as profile_mod
from twin.engine import TwinEngine, load_config
from twin.engine import load_config as twin_config

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
              name: str | None = None, dataset_id: str | None = None, interval: str | None = None,
              residual_ref="auto") -> Dataset:
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


def _residual_reference(ds: Dataset) -> dict | None:
    """Healthy residual baseline: shipped Normal month for Transformer-1, the generator's own Normal month for any
    other rated profile, and none (self-calibrate on the first week) when the rating itself is only estimated."""
    if ds.mode != "full":
        return None
    source = ds.asset.get("nameplate_source")
    if source == "asset.yaml":
        return sc.normal_reference(load_thresholds())
    if source == "estimated":
        return None
    return sc.normal_reference_for({**ds.asset, **_losses(ds.asset)})


# ---------------------------------------------------------------- generic transformer profile
def presets() -> list[dict]:
    """Example profiles for the rating panel: values, tags (Confirmed / Derived / IEC default / Assumed) and notes."""
    raw = yaml.safe_load((ROOT / "config" / "presets.yaml").read_text(encoding="utf-8"))
    out = []
    for p in raw:
        values = {k: v["value"] for k, v in p["profile"].items()}
        tags = {k: v["tag"] for k, v in p["profile"].items()}
        out.append({"id": p["id"], "label": p["label"], "description": " ".join(str(p["description"]).split()),
                    **resolve_profile(values, tags)})
    return out


def resolve_profile(values: dict, tags: dict | None = None) -> dict:
    """Complete a typed profile (rating, voltage, anything else known) into the full tagged parameter set."""
    a = profile.resolve({**values, "tags": dict(tags or {})})
    notes = a.pop("profile_notes", [])
    tg = a.pop("tags", {})
    a.pop("nameplate_source", None)
    return _jsonable({"values": a, "tags": tg, "notes": notes})


def simulate(scenario: str, values: dict, tags: dict | None = None, seed: int = 0, name: str | None = None,
             dataset_id: str | None = None, plant: str = "iec") -> Dataset:
    """Generate a SIMULATED scenario for ANY transformer profile and run it through the full pipeline.

    plant="iec" is the thermal library with perturbed parameters; plant="detailed" is the independent heat-balance
    model (twin/detailed.py), so the twin is tested against different physics."""
    from sim import generator
    if scenario not in generator.SCENARIO_IDS:
        raise ValueError(f"unknown scenario {scenario!r}; choose from {', '.join(generator.SCENARIO_IDS)}")
    asset = profile.resolve({**values, "tags": dict(tags or {})})
    label = str(asset.get("name") or f"{asset['rating_kVA']:g} kVA")
    trend, events = generator.generate(scenario, seed=int(seed), asset=asset, plant=plant)
    ref = "auto" if plant == "iec" else sc.normal_reference_for(asset, plant)
    dataset_id = dataset_id or f"u-{hashlib.sha1((scenario + label + str(time.time())).encode()).hexdigest()[:10]}"
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / "trend.csv"]
        trend.to_csv(paths[0], index=False)
        if len(events):
            paths.append(Path(tmp) / "events.csv")
            events.to_csv(paths[1], index=False)
        suffix = "" if plant == "iec" else " · detailed physics"
        return load_file(paths, asset=asset, name=name or f"{label} · scenario {scenario}{suffix} (SIMULATED)",
                         dataset_id=dataset_id, residual_ref=ref)


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
    profile columns (twin/thermal_profile.py COLUMNS), plus the Health Index series as health_score, health_band,
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
    """IEC 60076-7 thermal diagram and heat flow at the last sample at or before t (twin/thermal_profile.py).

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
    """Steady state of the twin at a load, ambient and cooling effectiveness (twin/thermal_profile.py whatif).

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


_WHATIF_REF: dict[str, dict | None] = {}  # healthy residual baseline per dataset (loading it is the slow part)
WHATIF_PROFILES = ("steady", "daily")


def whatif_day(dataset_id: str, t, load_pu: float, ambient_C: float, cooling: float = 1.0, voltage_pu: float = 1.0,
               pf: float = 0.95, unbalance_pct: float = 0.0, load_profile: str = "steady") -> dict:
    """A what-if run through the full pipeline: plant -> adapter -> twin -> analytics -> Health Index.

    The plant (sim/generator.py run_plant) is this dataset's transformer at the chosen load, ambient, cooling, voltage,
    power factor and phase unbalance; its readings go through the same adapter, twin and analytics as an uploaded file,
    so health, alerts and every frame column come from the same code as replay. steady: constant inputs for one day.
    daily: two days of this dataset's own hour-of-day load and ambient shape, scaled so the peaks equal load_pu and
    ambient_C (day 1 warms the plant up). Oil level and humidity start from the replay row at t.
    Returns frames-shaped columns plus `cursor` (steady: the end; daily: the hot-spot peak of day 2) and the alerts."""
    import tempfile
    from sim import generator
    if not 0 < load_pu <= 2:
        raise ValueError("load_pu must be within 0-2")
    if not -10 <= ambient_C <= 60:
        raise ValueError("ambient_C must be within -10..60")
    if not 0.05 <= cooling <= 1.5:
        raise ValueError("cooling must be within 0.05-1.5 (1 = radiators as designed)")
    if not 0.8 <= voltage_pu <= 1.2:
        raise ValueError("voltage_pu must be within 0.8-1.2")
    if not 0.5 <= pf <= 1.0:
        raise ValueError("pf must be within 0.5-1.0")
    if not 0 <= unbalance_pct <= 50:
        raise ValueError("unbalance_pct must be within 0-50")
    if load_profile not in WHATIF_PROFILES:
        raise ValueError(f"load_profile must be one of {', '.join(WHATIF_PROFILES)}")
    run = get_run(dataset_id)
    if run.mode in ("snapshot", "data_only") or "timestamp" not in run.trend:
        raise ValueError("a what-if day needs a dataset with a time series")
    asset = profile.complete({k: v for k, v in run.asset.items() if k not in ("tags", "profile_notes")})
    row = run.trend.iloc[_index_at(run, t) if t is not None else len(run.trend) - 1]
    days = 1 if load_profile == "steady" else 2
    idx = pd.date_range(row["timestamp"].normalize(), periods=96 * days, freq="15min")
    hour = np.asarray(idx.hour + idx.minute / 60, dtype=float)

    def shape(col: str) -> np.ndarray | None:  # this dataset's mean by hour of day, at the 15-min points
        if col not in run.trend or run.trend[col].isna().all():
            return None
        m = run.trend.groupby(run.trend["timestamp"].dt.hour)[col].mean().reindex(range(24)).interpolate(limit_direction="both")
        return np.interp(hour, np.arange(25), np.append(m.to_numpy(), m.iloc[0]))

    load = np.full(len(idx), float(load_pu))
    amb = np.full(len(idx), float(ambient_C))
    if load_profile == "daily":
        ls, as_ = shape("load_pu"), shape("amb_C")
        ls = ls if ls is not None and np.nanmax(ls) > 0 else 0.55 + 0.45 * generator._smooth_step(hour, 8, 18)
        load = load_pu * ls / np.nanmax(ls)
        amb = ambient_C + ((as_ - np.nanmax(as_)) if as_ is not None else -4 * (1 + np.cos(2 * np.pi * (hour - 15) / 24)))
    # reduced cooling scales the top-oil rise by cooling^(-x), as in whatif(); plant and twin both get it, so the
    # twin is the what-if transformer (it agrees with the steady answer) rather than a healthy one watching a fault
    p = _params(run)  # d_theta_or_K = rise + ambient surcharge; whatif() scales the sum
    asset["top_oil_rise_K"] = p["d_theta_or_K"] * float(cooling) ** -p["x"] - (p["d_theta_or_K"] - float(asset["top_oil_rise_K"]))
    n = len(idx)
    pc = generator.load_config()["plant"]
    rng = np.random.default_rng(0)  # the generator's sensor noise, seeded: same inputs give the same day
    i_ph = (load * float(asset["i_rated_A"]))[:, None] * (1 + np.array([1.0, 0.0, -1.0]) * unbalance_pct / 100)
    plant = generator.run_plant(i_ph.mean(axis=1), amb, idx, asset)
    oil, hs = plant["oil"].to_numpy(), plant["hs"].to_numpy()
    i_ph = i_ph * (1 + rng.normal(0, pc["noise_vi_frac"], (n, 3)))
    v_ln = voltage_pu * float(asset["lv_voltage_V"]) / np.sqrt(3) * (1 + rng.normal(0, pc["noise_vi_frac"], (n, 3)))
    pf = np.clip(pf + rng.normal(0, 0.005, n), 0.5, 1.0)
    s_kva = (v_ln * i_ph).sum(axis=1) / 1000
    ref_oil = row.get("OTI_C") if pd.notna(row.get("OTI_C")) else row.get("twin_oil_C")
    if pd.notna(row.get("OLI_pct")) and pd.notna(ref_oil):
        oli = float(row["OLI_pct"]) + pc["oil_level_per_C"] * (oil - float(ref_oil))
    else:
        oli = pc["oil_level_base_pct"] + pc["oil_level_per_C"] * (oil - 50)
    trend = pd.DataFrame({
        "timestamp": idx, "IR": i_ph[:, 0], "IY": i_ph[:, 1], "IB": i_ph[:, 2], "I_mean": i_ph.mean(axis=1),
        "IN": np.abs((i_ph * np.exp(1j * np.deg2rad([0, -120, 120]))).sum(axis=1)),
        "VR": v_ln[:, 0], "VY": v_ln[:, 1], "VB": v_ln[:, 2],
        "S_kVA": s_kva, "P_kW": s_kva * pf, "Q_kVAr": s_kva * np.sqrt(1 - pf ** 2), "PF": pf, "freq_Hz": 50.0,
        "OTI_C": oil + rng.normal(0, pc["noise_temp_C"], n), "WTI_C": hs + rng.normal(0, pc["noise_temp_C"], n),
        "ATI_C": amb + rng.normal(0, 0.3, n), "OLI_pct": np.clip(oli + rng.normal(0, 0.3, n), 0, 100)})
    num = trend.select_dtypes("number").columns
    trend[num] = trend[num].round(3)
    rh = float(row["RH_pct"]) if pd.notna(row.get("RH_pct")) else 60.0
    hourly = pd.date_range(idx[0], idx[-1] + pd.Timedelta(hours=1), freq="1h")
    wx = pd.DataFrame({"timestamp": hourly, "temp_C": np.interp(hourly.asi8, idx.asi8, amb), "rh_pct": rh})
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "whatif.csv"
        trend.to_csv(path, index=False)
        ds = adapter.load([path], asset=asset, weather=wx, source="whatif", simulated=True)
    if dataset_id not in _WHATIF_REF:
        _WHATIF_REF[dataset_id] = _residual_reference(ds)
    w = _build(f"whatif-{dataset_id}", "What-if", ds, residual_ref=_WHATIF_REF[dataset_id])
    df = pd.concat([w.trend.reset_index(drop=True),
                    profile_mod.compute(w.trend, w.asset, float(twin_config()["bottom_oil_ratio"])).reset_index(drop=True)], axis=1)
    if len(w.health_series):
        df = pd.concat([df, w.health_series.drop(columns=["timestamp"]).add_prefix("health_").reset_index(drop=True)], axis=1)
    last_day = df[df["timestamp"] >= idx[-1].normalize()]
    cursor = df["timestamp"].iloc[-1] if load_profile == "steady" else last_day.loc[last_day["twin_hs_C"].idxmax(), "timestamp"]
    return {"frames": df, "cursor": cursor, "load_profile": load_profile,
            "alerts": [{"timestamp": a.timestamp, "type": a.type, "severity": a.severity, "origin": a.origin,
                        "explanation": a.explanation} for a in w.analysis.alerts]}


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


# ---------------------------------------------------------------- the physics, made visible
def physics_chain(values: dict, tags: dict | None, load_pu: float, ambient_C: float) -> dict:
    return physics.steady_chain(profile.resolve({**values, "tags": dict(tags or {})}), load_pu, ambient_C)


def physics_step(values: dict, tags: dict | None, from_pu: float, to_pu: float, ambient_C: float, minutes: int) -> dict:
    return physics.step_response(profile.resolve({**values, "tags": dict(tags or {})}), from_pu, to_pu, ambient_C, minutes)


def physics_detailed(values: dict, tags: dict | None, from_pu: float, to_pu: float, ambient_C: float, minutes: int,
                     k_factor: float = 1.0, use_mass_capacity: bool = False) -> dict:
    return physics.compare_models(profile.resolve({**values, "tags": dict(tags or {})}), from_pu, to_pu, ambient_C, minutes,
                                  k_factor, use_mass_capacity)


def physics_ageing_models() -> dict:
    from twin import detailed
    return detailed.ageing_models()


def physics_whatif(dataset_id: str, load_mult: float, ambient_offset_C: float, rise_mult: float, model: str = "iec",
                   k_factor: float = 1.0):
    """Replay a dataset's own load and weather under changed conditions. Returns (series DataFrame, summary)."""
    run = get_run(dataset_id)
    if run.mode in ("snapshot", "data_only") or "timestamp" not in run.trend:
        raise ValueError("what-if needs a dataset with a load and ambient-temperature time series")
    asset = {k: v for k, v in run.asset.items() if k not in ("tags", "profile_notes")}
    asset["tags"] = run.asset.get("tags", {})
    return physics.whatif(run.trend, asset, load_mult, ambient_offset_C, rise_mult,
                          reference_life_h=float(load_config()["reference_life_h"]), model=model, k_factor=k_factor)


# ---------------------------------------------------------------- the picture at one moment, and the outlook
def brief(dataset_id: str, t) -> dict:
    """Status sentence, ranked diagnosis, maintenance work order and headroom at time t (analytics/brief.py)."""
    from analytics import brief as brief_mod
    return brief_mod.brief(get_run(dataset_id), t)


def outlook(dataset_id: str, t, runs: int = 500) -> dict:
    """Remaining-life distribution, 30-day risk and 24 h forecast from time t (twin/forecast.py). Seeded, so repeatable."""
    from twin import forecast
    run = get_run(dataset_id)
    if run.mode in ("snapshot", "data_only") or "timestamp" not in run.trend:
        raise ValueError("an outlook needs a dataset with a load and ambient-temperature time series")
    from twin.forecast import _in_zone
    t = _in_zone(t, run.trend)
    asset = {k: v for k, v in run.asset.items() if k != "profile_notes"}
    cfg = load_config()
    life = (run.summary.get("life_consumed_days") or {}).get("actual") or 0.0
    consumed_h = float(asset.get("years_in_service") or 0) * 8766.0 + float(life) * 24.0
    seed = int(hashlib.sha1(dataset_id.encode()).hexdigest()[:6], 16)
    return {
        "t": t.isoformat(),
        "rul": forecast.rul_distribution(asset, run.trend, t, consumed_h, float(cfg["reference_life_h"]), cfg["risk_years"], n=runs, seed=seed),
        "trip_risk_30d": forecast.trip_risk_30d(asset, run.trend, t, seed=seed),
        "forecast": forecast.forecast_24h(run.trend, asset, t),
    }

_ML_CACHE: dict = {}


def ml_view(dataset_id: str, t) -> dict:
    """Isolation Forest and Prophet second opinions at time t (twin/mlview.py). Cached per dataset and hour."""
    from twin import mlview
    from twin.forecast import _in_zone
    run = get_run(dataset_id)
    if run.mode in ("snapshot", "data_only") or "timestamp" not in run.trend:
        raise ValueError("the machine-learning checks need a time series")
    t = _in_zone(t, run.trend)
    key = (dataset_id, t.floor("1h").isoformat())
    if key not in _ML_CACHE:
        if len(_ML_CACHE) > 64:
            _ML_CACHE.clear()
        _ML_CACHE[key] = {"t": t.isoformat(), "isolation_forest": mlview.isolation_forest(run.trend, t),
                          "prophet": mlview.prophet_check(run.trend, t)}
    return _ML_CACHE[key]


# ---------------------------------------------------------------- reporting layer
def report(dataset_id: str, fmt: str = "html") -> tuple[bytes, str, str]:
    """(content, media type, file name) for the run: self-contained HTML, full CSV, or JSON (reports/report.py)."""
    from reports import report as rep
    if fmt not in ("html", "csv", "json"):
        raise ValueError("fmt must be html, csv or json")
    run = get_run(dataset_id)
    name = f"{dataset_id}-report"
    if fmt == "csv":
        return rep.build_csv(run).encode("utf-8"), "text/csv; charset=utf-8", f"{name}.csv"
    series_ok = run.mode not in ("snapshot", "data_only") and "timestamp" in run.trend and len(run.trend)
    end = run.trend["timestamp"].max() if series_ok else None
    b = brief(dataset_id, end) if series_ok else {"level": "nodata", "sentence": "This dataset has no time axis.", "diagnosis": [], "advice": None, "kpis": {}}
    o = None
    if series_ok:
        try:
            o = outlook(dataset_id, end)
        except ValueError:
            o = None
    if fmt == "json":
        return rep.to_json_text(rep.build_json(run, _jsonable(b), _jsonable(o))).encode("utf-8"), "application/json", f"{name}.json"
    return rep.build_html(run, b, o).encode("utf-8"), "text/html; charset=utf-8", f"{name}.html"


# ---------------------------------------------------------------- live ingestion (the path to real sensors)
_LIVE: dict[str, dict] = {}
LIVE_MAX_ROWS = 20000
LIVE_MAX_BATCH = 5000


def _check_session(session: str) -> None:
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", session or ""):
        raise ValueError("session must be 1 to 40 letters, digits, '-' or '_'")


def ingest(session: str, rows: list[dict], asset: dict | None = None) -> dict:
    """Append readings from a device or gateway to a live session and recompute its run.

    rows are dicts with any column names the adapter can map (timestamp, currents, voltages, oil and ambient temperature...).
    The session shows up as the dataset `u-live-<session>`, so every dashboard page works on it. The whole buffer is
    re-read through the same adapter as a file upload, so cleaning, units, flags and capabilities behave identically.
    """
    import tempfile
    _check_session(session)
    if not rows:
        raise ValueError("send at least one reading")
    if len(rows) > LIVE_MAX_BATCH:
        raise ValueError(f"send at most {LIVE_MAX_BATCH} readings per call")
    if not all(isinstance(r, dict) and r for r in rows):
        raise ValueError("each reading must be an object of column: value pairs")
    s = _LIVE.setdefault(session, {"rows": [], "asset": None})
    if asset is not None:
        s["asset"] = profile.resolve({**asset, "tags": {}})
    s["rows"] = (s["rows"] + [dict(r) for r in rows])[-LIVE_MAX_ROWS:]
    did = f"u-live-{session}"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "live.csv"
            pd.DataFrame(s["rows"]).to_csv(path, index=False)
            ds = load_file([path], asset=s["asset"] or "config/asset.yaml", name=f"Live feed: {session}", dataset_id=did)
    except Exception as e:
        if len(_LIVE[session]["rows"]) == len(rows):          # the first batch was unusable: forget the session
            _LIVE.pop(session, None)
        else:
            _LIVE[session]["rows"] = _LIVE[session]["rows"][:-len(rows)]   # drop the bad batch, keep the session
        raise ValueError(f"These readings could not be read ({e}). Send a timestamp and at least one load column, for example "
                         "I_mean or IR, IY, IB, plus ambient or oil temperature if you have them.") from None
    last = ds.trend["timestamp"].max() if "timestamp" in ds.trend and len(ds.trend) else None
    return {"dataset_id": did, "session": session, "rows_total": int(len(ds.trend)), "mode": ds.mode,
            "capabilities": ds.capabilities, "last_timestamp": None if last is None else last.isoformat()}


def end_live(session: str) -> bool:
    """Forget a live session and its cached run. The name is validated before anything touches the file system."""
    _check_session(session)
    did = f"u-live-{session}"
    target = (RUNS / did).resolve()
    if target.parent != RUNS.resolve():
        raise ValueError("bad session")
    gone = _LIVE.pop(session, None) is not None
    _MEM.pop(did, None)
    shutil.rmtree(target, ignore_errors=True)
    return gone
