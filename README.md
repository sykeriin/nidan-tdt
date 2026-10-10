# Digital Twin of a Distribution Transformer

PowerNext-AI 2026 (CPRI × MIT Bengaluru), Track 02. A software twin of **Transformer-1** (1000 kVA, 415 V, oil-filled,
MAHE Bengaluru campus). It ingests any operating dataset, runs an IEC 60076-7 thermal and ageing model alongside the
measured data, and watches the gap: alerts, Health Index, ageing/RUL and maintenance advice.

How it works: [`docs/BACKEND_FLOW.md`](docs/BACKEND_FLOW.md) · design: [`docs/FINAL_PRD.md`](docs/FINAL_PRD.md) · ingestion: [`docs/DATA_INGESTION_SPEC.md`](docs/DATA_INGESTION_SPEC.md) ·
assumptions: [`docs/assumptions.md`](docs/assumptions.md) · data provenance: [`data/PROVENANCE.md`](data/PROVENANCE.md)

## Run it

```powershell
uv venv --python 3.12 .venv            # or: py -3.12 -m venv .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.venv\Scripts\python -m pytest -q       # full suite, runs offline
```

| Command | Does |
|---|---|
| `python -m ingest.adapter inspect FILE…` / `load FILE… [--schema S] [--save-schema S]` | Any CSV/Excel → proposed mapping / canonical dataset + health report |
| `python -m ingest.kaggle_clean` | Kaggle raw files → `data/clean/kaggle.parquet` + health report + plausibility plot |
| `python -m sim.generator [N S1 …]` | Generated campus data → `data/generated/` (SIMULATED) |
| `python -m sim.plot` · `python -m twin.plot N S2` | Scenario plots · measured-vs-twin plots → `docs/figures/` |
| `python -m sim.fixtures` | Ingestion fixtures → `data/fixtures/` |
| `python -m eval.run_eval` | Lead-time and false-alarm table → `docs/figures/lead_time.md` |
| `python -m ingest.enrich fetch YEAR MONTH [SITE]` | Cache Open-Meteo weather (only command that needs network) |
| `python -m dt.api rebuild [ID…]` | Precompute dashboard runs (N, S1–S5, kaggle) → `data/cache/runs/` |
| `uvicorn server.app:app --port 8000` | API at `/api`, docs at `/docs`, React build (`web/dist` or `DT_WEB_DIST`) at `/` — see [`docs/API.md`](docs/API.md) |
| `python -m server.export_openapi` | OpenAPI schema → `docs/openapi.json` |

## Pipeline

```
any file(s) ──> ingest/ (adapter) ──> canonical Dataset ──> twin/ (engine) ──> analytics/ (pipeline) ──> AnalysisResult
 CSV/Excel,      map · units · time ·    trend + events +     IEC 60076-7 thermal,   rules · residual · electrical ·   alerts, recommendations,
 record files    derive · enrich ·       capabilities + mode   residual, fidelity,    oil · through-fault · sensor     Health Index
                 validate (dq_flags)     (full/meter_only/     ageing (expected vs    faults · health · recommend
                                         data_only/snapshot)   actual), RUL, plausibility
sim/replay.py streams the same rows: TwinEngine.step() + StreamAnalyzer.update() == batch run() + analyze().
```

```python
from ingest.adapter import load
from twin.engine import TwinEngine
from analytics.common import load_thresholds
from analytics.pipeline import analyze
from eval.scenarios import effective_caps

ds = load(["my_file.xlsx"])                       # asset defaults to config/asset.yaml
twin = TwinEngine().run(ds)                       # twin.attrs: plausibility, rul, life_consumed_days, drift_message
res = analyze(twin, ds.events, effective_caps(ds.capabilities, twin), load_thresholds())
```

## Layout

| Path | Owner | Contents |
|---|---|---|
| `contracts/` | P1+P3 | Canonical columns, capability keys, shared dataclasses (`models.py`) |
| `ingest/` | P1 | Tier 1 adapter: read, shape, time, map, units, derive, enrich (Open-Meteo cache), validate, capabilities, snapshot mode; Kaggle cleaning |
| `sim/` | P2/P1 | Generator (N, S1–S5), fixtures, plots, replay / IoT simulator |
| `twin/` | P2 | Library wrapper, engine (`run`/`step`), ageing, RUL, physics plausibility check |
| `analytics/` | P3 | Detectors, sensor-vs-asset, Health Index, recommendations, `analyze()` / `StreamAnalyzer` / `analyze_snapshot()` |
| `eval/` | P3 | Lead time, false alarms, real-data scenario provider (`scenarios.py`) |
| `config/` | all | `asset.yaml`, `scenarios.yaml`, `thresholds.yaml`, `health.yaml`, `twin.yaml`, `synonyms.yaml`, `schema/kaggle.yaml` |
| `data/` | P1 | `raw/` (Kaggle, ETT, weather), `clean/`, `generated/`, `fixtures/`, `cache/weather/`, `PROVENANCE.md` |
| `docs/` | all | PRD, ingestion spec, assumptions, P3 handoff, figures, `reference/` (organizers' problem statement and draft sheet) |
| `dt/` | P4/all | `api.py`: the single backend facade for the dashboard (DataFrames / contract dataclasses only) |
| `server/` | P4 | FastAPI wrapper: one endpoint per facade function, uploads, downsampling, CORS, static React build |
| `app/`, `alerts/`, `reports/` | P4 | Empty: React app, Telegram, PDF not built yet |

## Status

**Done and tested (backend, end to end):** ingestion of any CSV/Excel incl. per-record files · Kaggle cleaned with
provenance · generated scenarios N, S1–S5 · twin (batch == streaming) with expected vs actual ageing, RUL range,
fidelity drift, physics plausibility check · analytics: 0 false alarms on all scenarios, lead 126 h on cooling
degradation and 47 h on the slow leak vs plain thresholds (`docs/figures/lead_time.md`) · Kaggle bad sensors give
sensor alerts only · replay.

**Backend for the dashboard:** `dt/api.py` facade and `server/` FastAPI (one endpoint per function, uploads,
downsampling, OpenAPI in `docs/openapi.json`), self-test in CPRI's Excel format, ranked snapshot tables.

**Not built yet:** the React app itself (P4) · PDF report (`report.pdf` returns 501) · Telegram alerts ·
IsolationForest · breathing-stress index · Tier 2 ingestion (JSON/Parquet/ZIP, long/historian format, multi-asset).

**Known open issues:** Kaggle unbalance detector chatters (2,042 alerts) and the stuck-sensor rule over-fires on 1 °C
data (390) — P3 · Kaggle download date not recorded (`data/PROVENANCE.md`) · licence of committing the Kaggle files to
be decided (`docs/P3_HANDOFF.md`) · IS 1180 / IEC 60076-7 limits marked [To verify].

Everything generated is labelled **SIMULATED**; the Kaggle unit is a different, unrated transformer.
