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
from twin import physics, profile
from twin.engine import TwinEngine, load_config

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
