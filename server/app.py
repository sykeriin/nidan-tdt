"""HTTP wrapper around dt/api.py. No analytics here: one endpoint per facade function, plus upload plumbing,
time-range filtering and chart downsampling for the dashboard.

    uvicorn server.app:app --port 8000          # API at /api, docs at /docs, React build (if present) at /

React build: DT_WEB_DIST (default web/dist). Uploads: data/uploads/<dataset_id>/ + registry.json.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from dt import api
from server import schemas as S
from server.serialize import MAX_POINTS, plain, series, table, time_range

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "data" / "uploads"
REGISTRY = UPLOADS / "registry.json"
WEB_DIST = Path(os.environ.get("DT_WEB_DIST", ROOT / "web" / "dist"))
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000", "http://127.0.0.1:3000"]
ALLOWED_EXT = {".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".xls"}
MAX_UPLOAD_MB = 200

app = FastAPI(title="Distribution-transformer digital twin API", version="1.0.0",
              description="Wraps dt/api.py. Timestamps ISO 8601 with offset; NaN -> null. Everything generated is "
                          "SIMULATED (see `simulated` fields).")
app.add_middleware(CORSMiddleware, allow_origins=DEV_ORIGINS, allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- errors: readable 4xx
@app.exception_handler(KeyError)
async def _not_found(_: Request, exc: KeyError):
    return JSONResponse(status_code=404, content={"detail": str(exc.args[0]) if exc.args else "not found"})


@app.exception_handler(ValueError)
async def _bad_request(_: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(NotImplementedError)
async def _not_built(_: Request, exc: NotImplementedError):
    return JSONResponse(status_code=501, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
async def _invalid(_: Request, exc: RequestValidationError):
    msgs = [f"{'.'.join(str(p) for p in e.get('loc', []) if p != 'body')}: {e.get('msg')}" for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "; ".join(msgs)})


ERRORS = {400: {"model": S.ErrorModel}, 404: {"model": S.ErrorModel}, 422: {"model": S.ErrorModel}}


# ---------------------------------------------------------------- upload registry (server plumbing)
def _registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.exists() else {}


def _register(dataset_id: str, entry: dict) -> None:
    reg = _registry()
    reg[dataset_id] = entry
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(reg, indent=1), encoding="utf-8")


async def _save(files: list[UploadFile], folder: Path) -> list[Path]:
    if not files:
        raise ValueError("no file uploaded")
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for f in files:
        name = Path(f.filename or "upload.csv").name
        if Path(name).suffix.lower() not in ALLOWED_EXT:
            raise ValueError(f"unsupported file type {Path(name).suffix!r} for {name!r}; Tier 1 accepts "
                             f"{', '.join(sorted(ALLOWED_EXT))}")
        data = await f.read()
        if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
            raise ValueError(f"{name} is larger than {MAX_UPLOAD_MB} MB")
        p = folder / name
        p.write_bytes(data)
        out.append(p)
    return out


def _json_form(text: str | None, what: str):
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"{what} must be JSON: {e.msg} at position {e.pos}") from None


def _local(t):
    """Query times: naive = Asia/Kolkata (the data's zone)."""
    if t is None:
        return None
    t = pd.Timestamp(t)
    return t.tz_localize("Asia/Kolkata") if t.tzinfo is None else t


def _known(dataset_id: str) -> None:
    ids = set(api.list_datasets()["dataset_id"])
    if dataset_id not in ids:
        raise KeyError(f"unknown dataset {dataset_id!r}; GET /api/datasets lists the available ones")


# ---------------------------------------------------------------- endpoints (one per facade function)
@app.get("/api/datasets", response_model=list[S.DatasetInfoModel], tags=["datasets"])
def list_datasets():
    """api.list_datasets() — cached scenarios, Kaggle and uploads."""
    df = api.list_datasets()
    reg = _registry()
    rows = plain(df.to_dict("records"))
    for r in rows:
        r["files"] = reg.get(r["dataset_id"], {}).get("files")
    return rows


@app.post("/api/inspect", response_model=S.InspectResultModel, responses=ERRORS, tags=["import"])
async def inspect_file(files: Annotated[list[UploadFile], File(description="CSV/Excel file(s)")]):
    """api.inspect_file() — auto-mapping proposal for the Import page. Nothing is stored."""
    folder = UPLOADS / f"tmp-{uuid.uuid4().hex[:8]}"
    try:
        paths = await _save(files, folder)
        r = api.inspect_file(paths)
        return {"tables": plain(r.tables), "timestamp": plain(r.timestamp), "proposals": plain(r.proposals),
                "preview": table(r.preview), "warnings": r.warnings}
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@app.post("/api/datasets", response_model=S.DatasetModel, status_code=201, responses=ERRORS, tags=["import"])
async def load_file(
    files: Annotated[list[UploadFile], File(description="CSV/Excel file(s)")],
    name: Annotated[str | None, Form()] = None,
    mapping: Annotated[str | None, Form(description='JSON {"source col": {"to": "IR", "unit": "A"}}; omit = auto-map')] = None,
    asset: Annotated[str | None, Form(description='JSON {"rating_kVA": 1000, "lv_voltage_V": 415}; "estimate"; omit = asset.yaml')] = None,
    interval: Annotated[str | None, Form(description="records without time: assign timestamps every e.g. 15min (ASSUMED_TIME)")] = None,
):
    """api.load_file() — upload, map, run the twin and analytics, cache the run, register the dataset."""
    dataset_id = f"u-{uuid.uuid4().hex[:10]}"
    folder = UPLOADS / dataset_id
    try:
        paths = await _save(files, folder)
        a = _json_form(asset, "asset") if asset and asset != "estimate" else (None if asset == "estimate" else "config/asset.yaml")
        ds = api.load_file(paths, mapping=_json_form(mapping, "mapping"), asset=a, name=name,
                           dataset_id=dataset_id, interval=interval)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    _register(dataset_id, {"name": name or paths[0].name, "files": [p.name for p in paths],
                           "uploaded": datetime.now().astimezone().isoformat()})
    rep = {k: v for k, v in ds.health_report.items() if not isinstance(v, pd.DataFrame)}
    return {"dataset_id": dataset_id, "mode": ds.mode, "rows": len(ds.trend), "capabilities": ds.capabilities,
            "health_report": plain(rep), "asset": plain({k: v for k, v in ds.asset.items() if k != "tags"})}


@app.get("/api/datasets/{dataset_id}/run", response_model=S.RunModel, responses=ERRORS, tags=["run"])
def get_run(dataset_id: str,
            start: Annotated[datetime | None, Query(description="ISO 8601; naive = Asia/Kolkata")] = None,
            end: Annotated[datetime | None, Query(description="ISO 8601; naive = Asia/Kolkata")] = None,
            max_points: Annotated[int, Query(ge=10, le=MAX_POINTS)] = MAX_POINTS):
    """api.get_run() — summary, analysis, and every numeric trend/twin/health column as a series."""
    _known(dataset_id)
    run = api.get_run(dataset_id)
    start, end = _local(start), _local(end)
    if start is not None and end is not None and start > end:
        raise ValueError("start is after end")
    tr = time_range(run.trend, start, end)
    hs = time_range(run.health_series, start, end)
    ev = time_range(run.events, start, end) if len(run.events) else run.events
    ser, down = series(tr, max_points)
    hser, hdown = series(hs.drop(columns=["band"], errors="ignore"), max_points)
    bands = {"t": [pd.Timestamp(t).isoformat() for t in hs["timestamp"]], "band": list(hs["band"])} if len(hs) else {}
    records = table(api.snapshot_table(dataset_id)) if run.mode == "snapshot" else None
    return {"dataset_id": run.dataset_id, "name": run.name, "mode": run.mode, "capabilities": run.capabilities,
            "health_report": plain(run.health_report), "asset": plain(run.asset), "summary": plain(run.summary),
            "analysis": plain(run.analysis), "series": ser, "health_series": hser,
            "bands": bands if len(hs) <= max_points else {}, "events": table(ev), "records": records,
            "start": plain(tr["timestamp"].min()) if "timestamp" in tr and len(tr) else None,
            "end": plain(tr["timestamp"].max()) if "timestamp" in tr and len(tr) else None,
            "rows_in_range": len(tr), "max_points": max_points, "downsampled": bool(down or hdown)}


@app.get("/api/datasets/{dataset_id}/state", response_model=S.StateAtModel, responses=ERRORS, tags=["run"])
def state_at(dataset_id: str, t: Annotated[datetime, Query(description="ISO 8601; naive = Asia/Kolkata")]):
    """api.state_at() — twin, Health Index and the last 24 h of alerts at time t."""
    _known(dataset_id)
    return plain(api.state_at(dataset_id, _local(t)))


@app.get("/api/datasets/{dataset_id}/replay", responses={**ERRORS, 200: {"content": {"application/x-ndjson": {}},
         "description": "one StateAt JSON object per line"}}, tags=["run"])
def replay(dataset_id: str,
           speed: Annotated[float | None, Query(gt=0, description="data-seconds per wall-second; omit = no waiting")] = None,
           start: Annotated[datetime | None, Query()] = None,
           end: Annotated[datetime | None, Query()] = None,
           limit: Annotated[int, Query(ge=1, le=50000)] = 500,
           dropout: Annotated[float, Query(ge=0, lt=1, description="simulated comms loss (seeded)")] = 0.0,
           seed: int = 0):
    """api.replay() — NDJSON stream of StateAt objects."""
    _known(dataset_id)
    gen = api.replay(dataset_id, speed=speed, start=_local(start), end=_local(end), seed=seed, dropout=dropout)
    first = next(gen, None)   # surface errors (e.g. snapshot dataset) as 4xx before streaming starts

    def lines():
        n = 0
        for s in ([first] if first else []):
            n += 1
            yield json.dumps(plain(s)) + "\n"
        for s in gen:
            if n >= limit:
                break
            n += 1
            yield json.dumps(plain(s)) + "\n"
    return StreamingResponse(lines(), media_type="application/x-ndjson")


@app.get("/api/self-test", response_model=S.TableModel, tags=["self-test"])
def self_test():
    """api.self_test() — CPRI Excel format: reference vs software, diff, % diff, pass (<= 1 %), trip checks."""
    return table(api.self_test())


@app.get("/api/datasets/{dataset_id}/snapshot", response_model=S.TableModel, responses=ERRORS, tags=["run"])
def snapshot_table(dataset_id: str):
    """api.snapshot_table() — records (or daily peak operating points) ranked worst Health Index first."""
    _known(dataset_id)
    return table(api.snapshot_table(dataset_id))


@app.get("/api/datasets/{dataset_id}/report.pdf", responses={**ERRORS, 501: {"model": S.ErrorModel},
         200: {"content": {"application/pdf": {}}}}, tags=["reports"])
def report_pdf(dataset_id: str):
    """api.report_pdf() — not built yet: 501 with the reason."""
    _known(dataset_id)
    from fastapi import Response
    return Response(api.report_pdf(dataset_id), media_type="application/pdf")


@app.get("/api/health", tags=["meta"])
def healthcheck():
    return {"status": "ok", "web_build": WEB_DIST.is_dir()}


# ---------------------------------------------------------------- React production build (same origin)
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
else:
    @app.get("/", include_in_schema=False)
    def _no_build():
        return {"detail": f"React build not found at {WEB_DIST}. Build the web app (npm run build) or set "
                          "DT_WEB_DIST. API: /api, docs: /docs"}
