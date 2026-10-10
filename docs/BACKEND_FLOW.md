# How the backend works

One sentence: **any file goes in, it's mapped to one standard table, a physics twin of the transformer runs beside the
measured data, analytics watch the gap between them, and the results are served through one Python facade and a
FastAPI server.**

```
 ┌──────────────┐   ┌───────────────┐   ┌──────────────┐   ┌──────────────────┐   ┌─────────────┐   ┌───────────┐
 │ 1 DATA IN    │──>│ 2 INGEST      │──>│ 3 TWIN       │──>│ 4 ANALYTICS      │──>│ 5 FACADE    │──>│ 6 SERVER  │──> dashboard
 │ files, live, │   │ ingest/       │   │ twin/        │   │ analytics/       │   │ dt/api.py   │   │ server/   │
 │ generated    │   │ adapter       │   │ engine       │   │ pipeline         │   │ + run cache │   │ FastAPI   │
 └──────────────┘   └───────────────┘   └──────────────┘   └──────────────────┘   └─────────────┘   └───────────┘
        ▲                  │ Dataset            │ trend + twin cols    │ AnalysisResult        │ Run / StateAt      │ JSON
        │                  ▼                    ▼                      ▼                       ▼                    ▼
   sim/ generator     contracts/          contracts/            contracts/              data/cache/runs/    docs/openapi.json
   sim/ replay        canonical.py        canonical.py          models.py               (parquet + json)
```

## 1. Data in

| Source | What it is | Where |
|---|---|---|
| Uploaded files | Any CSV/TSV/TXT or Excel (all sheets), incl. per-test record files with no timestamp | `POST /api/datasets` → `data/uploads/` |
| Generated campus data | Transformer-1 (1000 kVA, 415 V) for April 2026, scenarios N, S1 overload, S2 cooling degradation, S3 unbalance, S4a oil leak, S4b oil theft, S5 through-faults. **SIMULATED** | `sim/generator.py` → `data/generated/` |
| Real field data | Kaggle "Distributed Transformer Monitoring": a different, unrated transformer | `data/raw/kaggle/` → cleaned `data/clean/kaggle.parquet` |
| Weather | Open-Meteo hourly temperature + humidity (Bengaluru Apr 2026, Hyderabad Jul 2019–Mar 2020), cached so everything runs offline | `ingest/enrich.py` → `data/cache/weather/` |
| Live / replay | Rows streamed one at a time (IoT simulator, seeded comms dropouts) | `sim/replay.py` |

The generator works like a real plant. It drives the IEC thermal library with *perturbed* parameters and adds sensor
noise, so the "measured" data is not the twin's own output. Faults are injected into this plant only, and ground
truth goes into `gt_*` columns.

## 2. Ingest: `ingest/` (the adapter)

Every source goes through one path: `adapter.load(paths, schema, asset)` → `Dataset`. For a single live row it's
`map_row()`.

| Step | Module | Does |
|---|---|---|
| Read | `read.py` | Sniffs the encoding and delimiter, skips metadata rows, reads every Excel sheet |
| Shape | `shape.py` | Classifies each table as trend / events / nameplate / records, merges files on time, turns event sheets into the canonical event table |
| Time | `time.py` | Finds the timestamp: ISO, day-first DD/MM (Indian default), epoch, or Excel serial. Assumes Asia/Kolkata. Dedupes: identical rows → one kept; conflicting rows → median, flagged |
| Map | `map.py` + `config/synonyms.yaml` | Proposes header → canonical column with a confidence score (exact > synonym > unit suffix like `Load_Current_A` > fuzzy), and resolves R/Y/B vs A/B/C. Ground-truth columns → `gt_*`, device alarms → `alarm_*`; both are quarantined from detectors |
| Units | `units.py` | Reads the unit from the header (`(°F)`, `[kA]`, `_kV`) or from the magnitude, and converts to A, V, °C, kW, % |
| Derive | `derive.py` | Per-phase currents from total current, kVA, P/PF or loading %; L-N voltage from L-L; S from V·I; loading %. Every derived value is flagged |
| Enrich | `enrich.py` | Ambient from ATI, else the Open-Meteo cache, else interpolation or climatology; RH from the cache; nameplate from `config/asset.yaml`, the UI form, or estimated from data |
| Validate | `validate.py` | Writes `dq_flags`; rows are never deleted. Flags: GAP, RANGE, JUMP (a temperature step not explained by a load step), STUCK, NEG, DUP_*, ATI_MISMATCH, DERIVED/IMPUTED/ASSUMED provenance |
| Capabilities | `capabilities.py` | Builds the capability matrix and picks the mode: `full` (has OTI), `meter_only` (no OTI: temperatures estimated), `data_only` (twin can't run), `snapshot` (records without time) |

Output contract: `contracts/canonical.py`, the canonical trend and event tables.

## 3. Twin: `twin/`

`TwinEngine(asset).run(dataset)` for batch, or `.step(row)` for streaming. Both give identical numbers; this is tested.

| Piece | Module | Does |
|---|---|---|
| Thermal model | `thermal.py` → **transformer-thermal-model** (Alliander, IEC 60076-7) | Top-oil and hot-spot temperature from the load (in **amps**) and ambient, with nominal parameters. After a gap of more than 2 h it restarts from steady state |
| Residual / fidelity | `engine.py` | Residual = measured OTI − twin top-oil. Fidelity is the rolling 24 h RMSE; above 3 °C it raises "model drift — check cooling / recalibrate" |
| Ageing | `ageing.py` | Paper ageing rate 2^((θh−98)/6), and equivalent days aged. **Expected** uses the twin hot-spot (healthy cooling). **Actual** uses measured OTI + twin winding gradient where OTI is trusted. The gap between them is the life a fault cost |
| RUL | `rul.py` + `config/twin.yaml` | Remaining life as a range from recent actual ageing. Reference life is 180,000 h [To verify]; the display caps at "> 40 years" |
| Plausibility | `plausibility.py` | Is the measured top-oil rise physically possible at this load? It's compared with an IEC band over plausible designs. It flags `IMPLAUSIBLE_RISE` and gives a per-channel verdict. On Kaggle it rejects the OTI sensor: 2 K measured vs ≥ 9 K possible |
| Snapshot | `engine.run_snapshot` | Records without time: each record is solved at steady state |

## 4. Analytics: `analytics/`

`analyze(df_twin, events, caps, thresholds, residual_reference)` → `AnalysisResult`. `StreamAnalyzer` does the same
live, and `analyze_snapshot` covers record files.

| Detector | Module | Catches |
|---|---|---|
| Rules + hysteresis | `rules.py` | Loading, over-current, top-oil, hot-spot, ageing-rate alarms (`config/thresholds.yaml`) |
| Residual | `residual.py` | Cooling degradation: measured − twin, normalised by the twin's rise. The threshold is calibrated on the Normal scenario (mean + 4σ, 2 h) |
| Electrical | `electrical.py` | Current/voltage unbalance, over/under voltage |
| Oil | `oil.py` | Low level, slow leak (slope), theft (a step that persists, with no thermal cause, night flag) |
| Through-fault | `through_fault.py` | Event-table I²t stress → "measure short-circuit impedance (%X) vs IS 1180" |
| Sensor vs asset | `sensor_faults.py` | Jump / range / stuck / dead / drift / implausible on a channel → `origin = sensor` ("check the device, not the transformer"). Untrusted channels are hidden from the asset detectors |
| Health Index | `health.py` + `config/health.yaml` | 0–100 from six sub-scores (thermal 30, ageing 25, loading 15, electrical 15, integrity 10, fault stress 5). Weights renormalise when a sub-score isn't available; a critical alarm caps the index at 40 |
| Recommendations | `recommend.py` | Each alert → a named test, urgency and rationale |

Evaluation (`eval/`): lead time vs plain thresholds and false alarms → `docs/figures/lead_time.md`. Result: 0 false
alarms; lead time 126 h on cooling degradation and 47 h on the slow leak.

## 5. Facade: `dt/api.py`

This is the one place a dashboard talks to. It returns only DataFrames or `contracts/models.py` dataclasses.

`list_datasets` · `inspect_file` · `load_file` · `get_run` · `state_at` · `replay` · `self_test` (CPRI Excel format) ·
`snapshot_table` · `report_pdf` (stub).

Runs are precomputed and cached in `data/cache/runs/<id>/` (`trend.parquet`, `events.parquet`,
`health_series.parquet`, `run.json`). Rebuild with `python -m dt.api rebuild`. An upload is computed once on load and
cached as `u-…`.

## 6. Server: `server/` (FastAPI)

`uvicorn server.app:app --port 8000` starts everything: `/api/…` (one endpoint per facade function), `/docs`, and a
frontend build from `web/dist` if one is present.

- **Responses:** Pydantic models mirror the contracts. Timestamps are ISO 8601 with offset and NaN is null.
- **Uploads:** multipart upload with a registry.
- **Run data:** a time-range filter and ≤ 2,000 points per chart series (min/max bucketing keeps peaks).
- **Errors and CORS:** readable 400/404/422/501 errors; CORS open for local development.
- **Schema and reference:** `docs/openapi.json`; full field reference in `docs/API.md`.

## One request, end to end

`GET /api/datasets/S2/run?start=2026-04-20&end=2026-04-27`:

1. `server.app.get_run` checks the id and calls `dt.api.get_run("S2")`.
2. The facade loads the cached run (computed earlier by: generator CSV → adapter → `TwinEngine.run` → `analyze` →
   `health.compute_series`).
3. The server filters the time range and downsamples each series to ≤ 2,000 points. Timestamps become ISO strings and
   NaN becomes null.
4. JSON goes back with the residual series, the `residual_drift` alert on 22 Apr 09:00 and its recommendation
   ("Inspect radiators and cooling", 7 days), the Health Index, life consumed (actual 1.82 d vs expected 1.36 d) and
   the plausibility verdict.

Upload path: `POST /api/datasets` saves the files → `dt.api.load_file` → `adapter.load` → `TwinEngine.run` →
`analyze` → cached → registered → available to every other endpoint.

## What we use for what

| Library / source | Used for |
|---|---|
| **transformer-thermal-model 0.6.0** (MPL-2.0) | IEC 60076-7 top-oil / hot-spot thermal model and paper ageing |
| **pandas, numpy** | All tables, time series, maths |
| **pyyaml** | Config files (`config/*.yaml`) |
| **openpyxl, xlrd** | Reading Excel uploads and the CPRI self-test sheet |
| **pyarrow** | Parquet: cleaned Kaggle data and the run cache |
| **requests** | Only for fetching Open-Meteo weather into the cache (`python -m ingest.enrich fetch …`); everything else is offline |
| **matplotlib** | Static figures in `docs/figures/` (scenarios, twin, plausibility) |
| **fastapi, uvicorn, python-multipart** | HTTP server, multipart uploads |
| **pytest, httpx** | Test suite and the API test client |
| **scikit-learn, plotly** | Listed in requirements but **not used yet** (the IsolationForest layer and frontend charts aren't built) |
| Open-Meteo archive (CC BY 4.0) | Ambient temperature and humidity |
| Kaggle dataset (sreshta140) | Real field data: adapter, sensor-fault and plausibility demos |

## Config that controls behaviour

| File | Controls |
|---|---|
| `config/asset.yaml` | Transformer-1 nameplate (rating, voltages, losses), every value tagged |
| `config/thresholds.yaml` | Operating alarm levels + bench (self-test only) values |
| `config/health.yaml` | Health Index weights, curves, bands, cap |
| `config/twin.yaml` | Restart gap, fidelity window/alert, reference life, RUL display cap |
| `config/scenarios.yaml` | Generator load profile, plant perturbation, fault magnitudes |
| `config/synonyms.yaml`, `config/schema/*.yaml` | Column mapping vocabulary and saved mappings |

## Not built yet

- `report_pdf` returns 501 (stub with its final signature).
- Telegram / status notification.
- IsolationForest anomaly layer.
- Breathing-stress index.
- Tier 2 ingestion: JSON/Parquet/ZIP, long historian format, multi-asset files.
- Kaggle's unbalance (2,042 alerts) and stuck-sensor (390) detectors chatter on real data and need episode merging.
