# Digital Twin of a Distribution Transformer

PowerNext-AI 2026 (CPRI × MIT Bengaluru), Track 02. A software twin for **any oil-filled distribution transformer**
(the demo unit is Transformer-1, 1000 kVA, 415 V, MAHE Bengaluru campus; enter any other rating or nameplate on the profile
page). It ingests any operating dataset, runs an IEC 60076-7 thermal and ageing model alongside the measured data, and
watches the gap: alerts, Health Index, diagnosis, remaining insulation life, maintenance advice and a downloadable report.

```powershell
start.bat          # Windows (macOS / Linux: ./start.sh): sets up on first run, then open http://localhost:8000
```

[`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) · [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) · [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md) ·
how the backend works: [`docs/BACKEND_FLOW.md`](docs/BACKEND_FLOW.md) · design: [`docs/FINAL_PRD.md`](docs/FINAL_PRD.md) · ingestion: [`docs/DATA_INGESTION_SPEC.md`](docs/DATA_INGESTION_SPEC.md) ·
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
| `python -m eval.selftest [--quick]` | Validation suite → `data/validation.json` and `docs/TEST_REPORT.md` (every validation number comes from here) |
| `cd web && npm run dev` / `npm run build` | Dashboard dev server (proxies `/api`) / production build served by uvicorn from `web/dist` |

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
| `twin/` | P2 | Library wrapper, engine (`run`/`step`), ageing, RUL, physics plausibility check; generic `profile.py`, `physics.py` (the equations made visible), `detailed.py` (independent heat-balance model), `forecast.py` (headroom, 24 h forecast, Monte Carlo life) |
| `analytics/` | P3 | Detectors, sensor-vs-asset, Health Index, recommendations, `analyze()` / `StreamAnalyzer` / `analyze_snapshot()`; `brief.py` (status sentence, ranked diagnosis, work order) |
| `eval/` | P3 | Lead time, false alarms, real-data scenario provider (`scenarios.py`), `selftest.py` |
| `config/` | all | `asset.yaml`, `scenarios.yaml`, `thresholds.yaml`, `health.yaml`, `twin.yaml`, `synonyms.yaml`, `schema/kaggle.yaml` |
| `data/` | P1 | `raw/` (Kaggle, ETT, weather), `clean/`, `generated/`, `fixtures/`, `cache/weather/`, `PROVENANCE.md` |
| `docs/` | all | PRD, ingestion spec, assumptions, P3 handoff, figures, `reference/` (organizers' problem statement and draft sheet) |
| `dt/` | P4/all | `api.py`: the single backend facade for the dashboard (DataFrames / contract dataclasses only) |
| `server/` | P4 | FastAPI wrapper: one endpoint per facade function, uploads, downsampling, CORS, static React build |
| `web/` | P4 | React + TypeScript dashboard (Vite). Replay in the browser, 3D twin, no CDN |
| `reports/` | P4 | `report.py`: self-contained HTML, CSV and JSON reports |
| `app/`, `alerts/` | P4 | Superseded Streamlit prototype; Telegram not built |

## Status

**Done and tested:** ingestion of any CSV/Excel incl. per-record files · a generic transformer profile (any rating, tagged
values, nameplate overrides defaults) · generated scenarios N, S1–S5 for any rating, with a choice of plant physics (standard,
or an independent detailed heat-balance model) · twin (batch == streaming) with expected vs actual ageing, fidelity drift and a
physics plausibility check · analytics with 0 false alarms on healthy months · ranked diagnosis, work order and plain-language
status · Monte Carlo remaining life, headroom, time to a limit, 24 h forecast · the Physics page · React dashboard with a 3D
heat-map twin, a flight-recorder replay dock, a guided demo and a printable report · self-test (`docs/TEST_REPORT.md`).

**Live data:** `POST /api/ingest` accepts readings from a device or gateway and shows them as a dataset (`u-live-<session>`).

**Not built:** MQTT / high-rate streaming · an Isolation Forest second opinion (tried, removed: noisy and weak) · server-side PDF (the HTML report prints to PDF) · Telegram alerts ·
breathing-stress index · optional channels (vibration, bushing, harmonic spectrum) · moisture / PD / DGA analysis · Tier 2
ingestion (JSON/Parquet/ZIP, long/historian format, multi-asset) · multi-transformer fleet views.

**Known open issues:** the Kaggle unbalance detector chatters and the stuck-sensor rule over-fires on 1 °C data (P3) ·
Kaggle
download date not recorded (`data/PROVENANCE.md`) · licence of committing the Kaggle files to be decided · IS 1180 /
IEC 60076-7 limits marked [To verify].

Everything generated is labelled **SIMULATED**; the Kaggle unit is a different, unrated transformer.
