# Backend API for the dashboard

Two layers, same functions:

- **`dt/api.py`**: the Python facade. Returns pandas DataFrames or dataclasses from `contracts/models.py`, never
  internal objects.
- **`server/`**: a FastAPI wrapper with one endpoint per facade function and no logic of its own. It adds upload
  plumbing, time-range filtering and chart downsampling. The schema is in [`docs/openapi.json`](openapi.json), and
  interactive docs are at `/docs` on a running server.

```powershell
python -m dt.api rebuild                 # precompute N, S1-S5 (S4a/S4b) and kaggle -> data/cache/runs/ (~10 s)
uvicorn server.app:app --port 8000       # API at /api, docs at /docs, React build (web/dist or DT_WEB_DIST) at /
python -m server.export_openapi          # -> docs/openapi.json
```

**JSON conventions:**
- Timestamps are ISO 8601 with an offset (`2026-04-22T09:00:00+05:30`). Query times without an offset are read as
  Asia/Kolkata.
- `NaN` is sent as `null`, and numpy numbers as plain JSON numbers.
- Tables are `{"columns": [...], "rows": [{...}]}`.
- Chart series are `{"t": [...], "v": [...]}`, with at most 2,000 points per series (min/max bucketing, so peaks and
  glitches survive).
- **Every generated record has `simulated: true`. Show the SIMULATED badge whenever it is true.**

**Dataset ids:**
- `N`, `S1`, `S2`, `S3`, `S4a` (leak), `S4b` (theft) and `S5` are Transformer-1, generated (SIMULATED).
- `kaggle` is the real field data from a different, unrated transformer (rating estimated from the data).
- `u-…` are uploads, cached the same way so they survive a restart.

Errors always come back as `{"detail": "readable message"}`:

| Status | Meaning |
|---|---|
| 400 | Bad input, e.g. an unsupported file, malformed mapping JSON, `t` before the first sample, `start` after `end`, or a snapshot dataset asked for time-based data |
| 404 | Unknown dataset id |
| 422 | Malformed parameter |
| 501 | Not built yet (`report.pdf`) |

---

## Functions and endpoints

| Facade | HTTP | Returns |
|---|---|---|
| `list_datasets()` | `GET /api/datasets` | DataFrame → `DatasetInfo[]` |
| `inspect_file(paths)` | `POST /api/inspect` (multipart `files`) | `InspectResult` |
| `load_file(paths, mapping, asset, name, dataset_id, interval)` | `POST /api/datasets` (multipart `files`, form `name`, `mapping`, `asset`, `interval`) | `Dataset` (201) |
| `get_run(dataset_id)` | `GET /api/datasets/{id}/run?start&end&max_points` | `Run` |
| `state_at(dataset_id, t)` | `GET /api/datasets/{id}/state?t` | `StateAt` |
| `replay(dataset_id, speed, start, end, seed, dropout)` | `GET /api/datasets/{id}/replay?speed&start&end&limit&dropout&seed` | iterator of `StateAt` → NDJSON stream |
| `self_test()` | `GET /api/self-test` | DataFrame → table |
| `snapshot_table(dataset_id)` | `GET /api/datasets/{id}/snapshot` | DataFrame → table |
| `report_pdf(dataset_id)` | `GET /api/datasets/{id}/report.pdf` | bytes. **Stub:** raises `NotImplementedError` → 501 |
| `rebuild(ids=None)` | CLI `python -m dt.api rebuild [ID …]` | list of rebuilt ids |

### `list_datasets()` / `GET /api/datasets`

**Fields:**
- `dataset_id`, `name`, `mode` (`full | meter_only | data_only | snapshot`)
- `rows`, `start`, `end` (tz-aware)
- `simulated`, `source` (`generated_sim | kaggle_real | organizer | …`)
- `health_score` (0–100) and `health_band` at the end of the data
- `cached`
- `files`: original file names (uploads only)

```json
{"dataset_id": "S2", "name": "Transformer-1 · scenario S2 (SIMULATED)", "mode": "full", "rows": 2880,
 "start": "2026-04-01T00:00:00+05:30", "end": "2026-04-30T23:45:00+05:30", "simulated": true,
 "source": "generated_sim", "health_score": 100.0, "health_band": "Green", "cached": true, "files": null}
```

### `inspect_file(paths)` / `POST /api/inspect`

This is the Import page proposal; nothing is stored. It returns:
- `tables`: name, role (`trend | events | nameplate | records | other`), rows and columns for each table
- `timestamp`: the detected column, format and parse percentage
- `proposals`: for each source column, the `canonical` target (null when confidence is below 0.6), `proposed`,
  `confidence`, the detected `unit` and the `unit_options`
- `preview`: the first 10 rows
- `warnings`

For a records file there is no time column, so it returns `timestamp.column: null` and a snapshot-mode warning.

```json
{"timestamp": {"column": "Date Time", "format": "day_first", "parsed_ok_pct": 100.0},
 "proposals": [{"source": "L1 Current (A)", "canonical": "IR", "proposed": "IR", "confidence": 0.9, "unit": "A",
                "unit_options": ["A", "kA"]}, "…"], "warnings": []}
```

### `load_file(...)` / `POST /api/datasets`

This uploads the file(s), maps them, runs the twin and analytics, caches the run and registers the dataset.

**Form fields:**
- `mapping`: JSON `{"source col": {"to": "IR", "unit": "A"}}`, taken from the edited proposals. Omit it to auto-map.
- `asset`:
  - JSON from the rating form, e.g. `{"rating_kVA": 250, "lv_voltage_V": 415}`
  - `"estimate"` to estimate from the data (red banner)
  - omit it to use `config/asset.yaml` (Transformer-1)
- `interval`: for records without time, assigns timestamps at this spacing (e.g. `15min`), flagged `ASSUMED_TIME`.

**Returns** `dataset_id`, `mode`, `rows`, `capabilities`, `health_report` (the Data Health page: mapping, unit
conversions, derived channels, flag counts, warnings, nameplate source) and `asset`. Missing losses are scaled from
Transformer-1's ratios (`losses_source`, [Assumed]).

### `get_run(dataset_id)` / `GET /api/datasets/{id}/run`

**Top level:**
- `dataset_id`, `name`, `mode`, `capabilities`, `health_report`, `asset`
- `start`, `end`, `rows_in_range`, `max_points`, `downsampled`

**`series`**: one entry per numeric column of the trend:

| Column(s) | Unit / meaning |
|---|---|
| `IR` `IY` `IB` `I_mean` `IN` | A (LV) |
| `VR` `VY` `VB` | V phase-neutral |
| `VRY` `VYB` `VBR` | V line-line |
| `S_kVA` / `P_kW` / `Q_kVAr` | kVA / kW / kVAr |
| `PF` | – |
| `freq_Hz` | Hz |
| `loading_pct` | % of rated |
| `OTI_C` `WTI_C` `ATI_C` `amb_C` | °C |
| `RH_pct` `OLI_pct` | % |
| `twin_oil_C` `twin_hs_C` `hs_ageing_C` | °C |
| `residual_oil_C` | K (measured − twin) |
| `fidelity_rmse_C` | K, rolling 24 h |
| `load_pu` | pu |
| `aging_rate` | relative to 98 °C (expected, twin) |
| `aging_rate_actual` | relative to 98 °C (measured OTI + gradient) |
| `days_aged_cum` / `days_aged_actual_cum` | equivalent days |
| `rise_low_K` `rise_high_K` | K, physics band |
| `implausible_rise` `twin_restart` `fidelity_alert` | 0/1 |
| `dt_min` | min |

**`health_series`**: `score` and the sub-scores `thermal`, `ageing`, `loading`, `electrical`, `integrity`,
`fault_stress` (0–100), plus `capped` (0/1). `bands` gives the band per health-series time.

**`analysis`** (`AnalysisResult`):
- `alerts[]`: `id`, `timestamp`, `module`, `type`, `severity`, `origin` (`asset | sensor`), `detector`, `value`,
  `threshold`, `explanation`, `recommendation_id`, `simulated`, `lead_time_h`
- `recommendations[]`: `id`, `action`, `test`, `urgency`, `rationale`, `alert_id`, `standard_ref`
- `health`: `score`, `band`, `components`, `weights`, `capped`
- `rul`: `years_low`, `years_high`, `risk`, `consumed_days`, `recent_rate` (raw; display with `summary.rul_display`)
- `fidelity_rmse_C` (K)

**`summary`:**
- `plausibility.OTI_C` (`plausible | suspect | not checked`)
- `life_consumed_days`: `expected`, `actual`, `actual_minus_expected`, `measured_share`
- `rul_display` (capped at "> 40 years")
- `drift_message`, `first_drift_alert`, `fidelity_rmse_C_last`
- snapshot mode: `disabled` (feature → reason)

**`events`**: `timestamp`, `event_type`, `phase`, `peak_pu`, `duration_ms`, `i2t_pu2s` (pu²·s).

**`records`**: snapshot mode only; the `snapshot_table` rows.

```json
{"dataset_id": "S2", "mode": "full", "rows_in_range": 5, "downsampled": false, "max_points": 2000,
 "start": "2026-04-22T08:00:00+05:30", "end": "2026-04-22T09:00:00+05:30",
 "series": {"OTI_C": {"t": ["2026-04-22T08:00:00+05:30", "…", "2026-04-22T09:00:00+05:30"],
                      "v": [43.253, 43.776, 45.344, 46.812, 47.835]}, "…": {}},
 "summary": {"plausibility": {"OTI_C": "plausible", "implausible_fraction": 0.033, "evaluable_rows": 2880},
             "rul_display": "RUL > 40 years",
             "life_consumed_days": {"expected": 1.365, "actual": 1.816, "actual_minus_expected": 0.452, "measured_share": 0.967},
             "drift_message": "model drift — check cooling / recalibrate", "first_drift_alert": "2026-04-25T05:30:00+05:30"},
 "analysis": {"alerts": [{"id": "residual_drift-20260422T0900", "timestamp": "2026-04-22T09:00:00+05:30",
                          "module": "insulation", "type": "residual_drift", "severity": "warning", "origin": "asset",
                          "detector": "residual", "value": 0.0502, "threshold": 0.046, "explanation": "Measured top-oil … Possible cooling degradation.",
                          "recommendation_id": "rec-residual_drift-20260422T0900", "simulated": true, "lead_time_h": null}],
              "recommendations": [{"id": "rec-residual_drift-20260422T0900", "action": "Inspect radiators and cooling; check oil level",
                                   "test": "Radiator and cooling inspection; oil level check", "urgency": "7d", "…": "…"}],
              "health": {"score": 100.0, "band": "Green", "components": {"thermal": 100.0, "…": 100.0}, "capped": false},
              "rul": {"years_low": 54.25, "years_high": 1000.0, "risk": "Low", "consumed_days": 1097.57, "recent_rate": 0.1352}}}
```

### `state_at(dataset_id, t)` / `GET /api/datasets/{id}/state?t=`

This is the state at the last sample at or before `t`:
- `row`: measured canonical values
- `twin`: the twin columns
- `health`: the Health Index at that sample, with sub-scores
- `alerts`: alerts raised in the 24 h up to `t`
- `mode`, `simulated`

It returns 400 for a snapshot dataset or a `t` before the first sample.

```json
{"timestamp": "2026-04-22T09:00:00+05:30", "row": {"I_mean": 741.23, "OTI_C": 47.835, "amb_C": 30.389, "dq_flags": "IMPUTED_RH", "…": "…"},
 "twin": {"twin_oil_C": 46.868, "residual_oil_C": 0.967, "aging_rate_actual": 0.0096, "ageing_source": "measured", "…": "…"},
 "mode": "full", "health": {"score": 100.0, "band": "Green", "…": "…"}, "alerts": [{"type": "residual_drift", "…": "…"}], "simulated": true}
```

### `replay(...)` / `GET /api/datasets/{id}/replay`

This sends one `StateAt` JSON object per line (`application/x-ndjson`).
- `speed` is data-seconds per wall-second (900 = one 15-min row per second); omit it for no waiting.
- `limit` caps the number of lines (default 500).
- `dropout` and `seed` simulate comms loss; the same seed gives the same stream.

It serves the precomputed run. That is exact: replay → `step()` → `StreamAnalyzer` equals the batch run
(`tests/test_integration_e2e.py`).

```
{"timestamp": "2026-04-01T00:00:00+05:30", "row": {"IR": 347.286, "…": "…"}, "twin": {"…": "…"}, "health": {"…": "…"}, "alerts": [], "simulated": true}
{"timestamp": "2026-04-01T00:15:00+05:30", "…": "…"}
```

### `self_test()` / `GET /api/self-test`

This is the self-test panel in CPRI's Excel format (`docs/reference/Draft Data for Condition Monitoring.xlsx`).
- **Columns:** `section` (`measurement | current_trip | temperature_trip | software_trip_check`), `item`, `unit`,
  `setting`, `reference`, `software`, `diff` (= software − reference), `diff_pct`, `pass` (|diff_pct| ≤ 1).
- **`software_trip_check`** ramps through the bench set points and confirms our comparators trip exactly at 50 A and
  60 °C.
- **Bench values are self-test only; they are never operating alarms.**

```json
{"section": "measurement", "item": "CHANNEL-A IR", "unit": "A", "setting": null, "reference": 49.79,
 "software": 49.92, "diff": 0.13, "diff_pct": 0.2611, "pass": true}
```

### `snapshot_table(dataset_id)` / `GET /api/datasets/{id}/snapshot`

This ranks entries worst Health Index first.
- **Snapshot datasets:** every record (`record_id`).
- **Time series:** one operating point per day (the highest-load sample), so the worst days come first.

**Columns:**
- `rank`, `record_id`, `load_pu`, `amb_C`, `OTI_C`
- `twin_oil_C`, `twin_hs_C`, `residual_oil_C`, `implausible_rise`, `dq_flags`
- `score`, `band`, and the sub-scores

```json
{"rank": 1, "record_id": "2026-04-24 13:30", "load_pu": 1.106, "amb_C": 35.19, "OTI_C": 85.84, "twin_oil_C": 87.48,
 "twin_hs_C": 119.84, "residual_oil_C": -1.64, "implausible_rise": false, "score": 40.7, "band": "Red",
 "thermal": 30.3, "ageing": 18.4, "loading": 0.0, "electrical": 100.0, "integrity": 100.0, "fault_stress": null}
```

### `report_pdf(dataset_id)` / `GET /api/datasets/{id}/report.pdf`

The signature is final, but the function isn't built yet (P4: no PDF library chosen). It raises `NotImplementedError`,
which the server returns as **501** `{"detail": "report_pdf is not built yet …"}`.

---

## Which capability flags hide which panels

`capabilities` comes with every run. **Hide or grey out a panel when its flag is false, and show the reason.** Never
crash on a missing channel.

| Flag | When false | Panels affected |
|---|---|---|
| `thermal_twin` | No current or no ambient: `mode = data_only` | All twin traces (twin top-oil, hot-spot), ageing, RUL, life consumed, plausibility. Only raw data and data-quality views remain |
| `residual_fidelity` | No OTI (`meter_only`), or OTI failed the physics plausibility check (`summary.plausibility.OTI_C == "suspect"`) | Residual chart, fidelity RMSE and drift banner, cooling-degradation module. In meter-only mode show "temperatures estimated from load + ambient". For a suspect OTI show the plausibility verdict instead |
| `wti_check` | No measured winding/hot-spot temperature | The measured hot-spot trace (the twin hot-spot is still shown) |
| `unbalance` | Fewer than 3 measured phase currents | R/Y/B current unbalance chart and unbalance tile ("needs per-phase currents") |
| `voltage_quality` | No per-phase voltages | Voltage chart, voltage unbalance, over/under-voltage |
| `neutral_measured` | No IN | Neutral current trace: show "proxy from unbalance", labelled proxy |
| `oil_leak_theft` | No oil level | Oil-level chart, leak vs theft module. Also check `drift_sensor` / `stuck_sensor` alerts on `OLI_pct`: a drifting gauge shows a data-quality note, not leak alerts |
| `through_fault` | No event log | Through-fault log, cumulative I²t stress, %X recommendation tile ("needs event log") |
| `breathing_index` | No RH | Breathing-stress tile (the index itself isn't built yet) |
| `ageing_rul` | Twin can't run | Ageing rate, life consumed, RUL tiles |
| `lead_time_eval` | No ground truth (real data) | Lead-time table (generated scenarios only) |
| `mode == "snapshot"` | Records without time | Show the ranked `records` table instead of time charts. Time panels are off for the reasons in `summary.disabled` / `health_report.disabled` |

Use `alert.origin == "sensor"` for "check the device, not the transformer" styling. Use `simulated` for the
SIMULATED badge.

---

## Generic transformer profile and physics

A profile is any subset of nameplate numbers (`rating_kVA` or `i_rated_A` is required). `twin/profile.py` completes it
and tags every value: `User input` / `Confirmed`, `Calculated` (rated current), `Derived` (load/no-load loss split from
the total losses at 50 % and 100 % load), `IEC 60076-7 default`, `Assumed`. A nameplate value always beats a default.

| Endpoint | Body | Returns |
|---|---|---|
| `GET /api/presets` | none | Example profiles (Transformer-1, a nameplate-derived 1250 kVA, generic 250/630/1600 kVA) with `values`, `tags`, `notes` |
| `POST /api/profile` | `{values, tags?}` | The complete tagged profile and notes explaining each derivation |
| `POST /api/simulate` | `{scenario, values, tags?, seed?, name?}` | Generates a SIMULATED scenario for that rating and runs the full pipeline. 201 with the new `dataset_id` (read it with `/run`) |
| `POST /api/physics/chain` | `{values, tags?, load_pu, ambient_C}` | Six calculation steps (formula, this asset's numbers, result), hot spot, ageing rate, and a check against the thermal library's own steady state |
| `POST /api/physics/step` | `{values, tags?, from_pu, to_pu, ambient_C, minutes}` | Top-oil and hot-spot curves after a load step, plus the time constants |
| `POST /api/datasets/{id}/whatif` | `{load_mult, ambient_offset_C, rise_mult}` | The dataset's own load and weather history replayed under changed conditions: series (`base_*`, `whatif_*`) and a summary (peak temperatures, hours above 98 °C, ageing, life used) |

The residual baseline is generated per transformer: for any rated profile the generator's healthy Normal month on that
asset (its own rating, losses and thermal parameters) is run through the twin. When only an estimated rating is known,
the detector self-calibrates on the first week instead.


---

## Moment, outlook, reports, live feed and the detailed physics

| Endpoint | Returns |
|---|---|
| `GET /api/datasets/{id}/brief?t=` | `level` (good / watch / critical), the plain-language `sentence`, ranked `diagnosis` (evidence and share per fault class, with unobservable classes marked), the `advice` work order (priority, schedule, actions with tests) and `kpis` (headroom, time to a limit, ageing, residual %, unbalance) at time `t` |
| `GET /api/datasets/{id}/outlook?t=` | Monte Carlo remaining insulation life (`years_p10/p50/p90`, risk class, fan chart), 30-day limit probability, and the 24 h forecast with its band. Seeded per dataset, so repeatable |
| `GET /api/datasets/{id}/report?fmt=html\|csv\|json[&download=true]` | The self-contained HTML report (inline SVG, no external files), the full CSV (every sample with Health Index, residual and alert flags), or JSON. `report.pdf` still returns 501: print the HTML to PDF |
| `POST /api/ingest` | `{session, rows[], asset?}`: append device readings; creates or updates the dataset `u-live-<session>`. Rows may use any column names the adapter can map. 400 with a readable reason if the readings cannot be read |
| `DELETE /api/ingest/{session}` | Forget a live session |
| `POST /api/physics/detailed` | The IEC model and the detailed heat-balance model on one load step, with the loss breakdown, viscosity and time constants |
| `GET /api/physics/ageing-models` | The 6 K rule and Arrhenius ageing curves |
| `POST /api/simulate` | Now also takes `plant`: `iec` (default) or `detailed` |
| `POST /api/datasets/{id}/whatif` | Now also takes `model` (`iec` / `detailed`) and `k_factor` (harmonics, detailed model only) |

Query times without an offset are Asia/Kolkata; times with an offset (the browser sends UTC) are converted to the data's own zone before any hour-of-day logic.
