# Architecture

A digital twin for condition monitoring of **any oil-filled distribution transformer**. A physics model runs next to the
measured data, and the analytics watch the gap between them. Block names follow the organizers' reference architecture.

```
Physical transformer       Data acquisition            Digital twin                       Analytics and advice
(V, I, kVA, oil temp,      ingest/                     1 Electrical model                 Condition monitoring
 ambient, oil level…)      read · shape · time ·       2 Thermal model (IEC 60076-7)      Anomaly detection
        │                  map · units · derive ·      3 Ageing model                     Health Index
        │  CSV / Excel     enrich · validate           4 Statistical detectors            │
        ▼  uploads, the         │                             │                              ▼
 simulator, replay ───────▶ canonical Dataset ───────────────┘                         Fault prediction (diagnosis)
 (live sensors:              trend + events +                                          RUL and risk (Monte Carlo)
  POST /api/ingest)         capabilities + mode                                       Maintenance advice
                                                                                              │
                                      dt/api.py  (one facade)  ◀──────────────────────────────┘
                                          │
                              server/ (FastAPI, /api)  ──▶  web/ (React dashboard)   ·   reports/ (HTML, CSV, JSON)
```

## Layers and where they live

| Block | Code | What it does |
|---|---|---|
| Data acquisition | `ingest/` | Reads CSV/Excel (all sheets), maps columns by synonym and range with a confidence score, converts units, parses any common time format, derives missing channels (always flagged), fills ambient from a cached weather record, and flags problems (`dq_flags`). Output is a canonical `Dataset`. |
| Capability matrix | `ingest/capabilities.py` | Decides what the data supports (twin, residual, unbalance, voltage quality, oil level, through-fault, ageing) and a **mode**: `full`, `meter_only` (no oil sensor: temperatures are estimated), `data_only`, or `snapshot` (records without time). Missing data turns features off and says why; it never crashes a page. |
| Transformer profile | `twin/profile.py`, `config/presets.yaml` | One generic profile: rating and voltage are enough, the nameplate overrides everything else, and every value carries a source tag (Confirmed, Calculated, Derived, IEC default, Assumed). |
| Electrical model | `ingest/derive.py`, `analytics/electrical.py` | Loading, rated current, phase and voltage unbalance, voltage deviation, derived per-phase currents. |
| Thermal model | `twin/thermal.py`, `twin/engine.py` | IEC 60076-7 top-oil and hot-spot model through the Alliander library. `run()` (batch) and `step()` (streaming) give identical numbers. |
| Ageing model | `twin/ageing.py`, `twin/rul.py` | Insulation ageing from the hot spot, expected (healthy twin) and actual (measured oil), and life used. |
| Physics plausibility | `twin/plausibility.py` | Asks whether a temperature sensor can be telling the truth. A sensor that cannot is excluded rather than learned from. |
| Detailed physics | `twin/detailed.py` | A second, independent heat-balance model with temperature-dependent losses. Used as the "real" transformer in simulations so the twin faces different physics. |
| Statistical detectors | `analytics/rules.py`, `residual.py`, `sensor_faults.py`, `oil.py`, `through_fault.py` | Threshold rules with hysteresis, a load-normalised residual detector, sensor-versus-asset classification, oil leak versus theft, through-fault stress. |
| Health Index | `analytics/health.py` | Six explainable sub-scores, renormalised over what is available, with a weakest-link cap. |
| Diagnosis, advice | `analytics/brief.py`, `analytics/recommend.py` | Ranked evidence per fault class, a work-order style recommendation, and a plain-language status sentence. |
| Outlook | `twin/forecast.py` | Headroom, time to a limit, 24 h forecast, Monte Carlo remaining life (P10/P50/P90), 30-day limit risk. |
| Physics showcase | `twin/physics.py` | The IEC equations with this transformer's numbers, a load-step response, what-if replays. |
| Simulator | `sim/generator.py`, `sim/replay.py` | Seven scenarios for any rating: a "plant" with perturbed parameters (or the detailed model) plus sensor noise, with faults injected into the plant only. Replay streams canonical rows. |
| Facade, API | `dt/api.py`, `server/` | One function per dashboard need, wrapped by FastAPI with readable errors, uploads and downsampling. |
| Live ingestion | `dt/api.py` (`ingest`), `POST /api/ingest` | A device or gateway posts readings; they are re-read through the same adapter as an upload and appear as the dataset `u-live-<session>`, so every page works on a live feed. |
| Dashboard | `web/` | React, TypeScript, no CDN. Replay runs in the browser. Shows what the API returns and computes no engineering values itself. |
| Reporting | `reports/report.py` | Self-contained print-ready HTML (inline SVG charts), a full CSV, and JSON. |
| Validation | `eval/selftest.py` | Produces every validation number in `docs/TEST_REPORT.md`. |

## Design rules

1. **Physics first.** Alerts come from the twin's residual and from rules. Statistical detection is a supporting signal.
2. **Calibrate nothing silently.** The twin is driven by nameplate values and standard defaults. It is not fitted to the data, so a faulty sensor is never learned as normal.
3. **Never invent values.** A missing channel switches a feature off with a reason. Derived, estimated and assumed values are flagged and listed.
4. **Ground truth stays out.** `gt_*` and device `alarm_*` columns are quarantined; detectors never see them (asserted in the pipeline).
5. **Honest labelling.** Anything generated is marked SIMULATED everywhere it appears, including the report.
6. **Offline.** Fonts, the 3D model, charts and the report need no network at run time.

## Data flow for one request

`GET /api/datasets/{id}/run` returns the cached result of: adapter output → `TwinEngine.run` → `analyze` → Health Index series.
The dashboard fetches it once and replays it locally by moving a time cursor. `brief` and `outlook` are computed on the server for
the cursor time (cached per 15 minutes and per hour). Uploads and simulations are cached the same way, so they survive a restart.

## Not built

- **MQTT bridge and streaming transport.** Live ingestion is HTTP: a gateway posts batches, and the whole session buffer (up to 20,000 readings) is re-analysed on each post. That suits readings every few minutes; a high-rate stream would need incremental analysis (the streaming engine and analyzer exist, but the dashboard path does not use them).
- **Isolation Forest second opinion.** It was built and tested, then removed: on one healthy month it raised 54 episodes and it caught almost none of the injected faults, so it added noise rather than information.
- **PDF generation on the server.** The HTML report prints to PDF from any browser.
- **Optional channels** (vibration, bushing temperature, harmonic spectrum) and moisture/PD/DGA analysis.
- **Multi-transformer fleet views.**
