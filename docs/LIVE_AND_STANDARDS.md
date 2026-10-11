# Live transformer, India standards, report and blueprint

Everything on the live transformer is **SIMULATED**. The replay datasets (S1 to S5, Kaggle, uploads) are untouched and are only used when you pick them in the Source menu.

## Sources in the dashboard

The dashboard opens on **Live transformer (simulated)**. It is a source, not a dataset: it is not listed with the replay datasets and is never written to disk. A background ticker
(`server/live.py`) advances the plant; the dashboard calls `POST /api/live/sync`, which rebuilds the `live` run from the readings so far, and then every page (Circuit, Diagnose with
Isolation Forest and Prophet, Simulate, part popovers, Condition) works on it. The **Live / Held** chip follows the newest reading or holds the timeline.

`?ds=S2` (or any dataset id) still opens that replay dataset.

## One server, three clients

| Client | How it connects |
|---|---|
| Dashboard | `POST /api/live/sync`, then the usual `/api/datasets/live/...` calls |
| Tablet (`/?view=tablet`, TX Alerts "Open twin view") | `GET /api/live/stream` (NDJSON), `POST /api/live/inject`, `/clear`, `/service` |
| Phone (TX Alerts app, PWA) | polls `GET /api/companion/test-alerts`; live alerts carry `live: true` and show as real alerts, test alerts show as TEST |
| Any | `GET /api/status`: server time, ticker state, tick, injections, newest alert number |

Any number of clients can stream at once; they all watch the same ticks. The ticker rests after 45 s with no client and wakes on the next request. The Android app takes
several backend URLs separated by commas and uses the first that answers.

## India profile (config/thresholds.yaml)

Limits follow IS 2026 (transformers), IS 1180 (distribution transformers), IS 6600 (loading guide, the Indian version of IEC 60076-7), IS 1866 (oil maintenance) and CEA.
Each entry in the file is tagged `[Standard]`, `[Practice]` or `[Assumed]`. **Standard** values follow the clause; **Practice** are common utility settings; **Assumed** are
starting values. Confirm Practice and Assumed ones with your utility before relying on them.

| Checklist item | Where it is covered |
|---|---|
| Short circuit fault | `short_circuit` injection, alert `short_circuit_trip` (above 10 pu), load trips off |
| Overload | alerts `loading_high`, `overcurrent`; condition card |
| Thermal capacity | condition card: load that keeps the hot spot at 98 and 120 °C at today's ambient |
| Hot-spot temperature | alert `hot_spot_high`; condition card |
| Insulation failure, turn to turn | `insulation_turn` injection, alert `turn_fault` (winding hotter than the twin says, oil normal) |
| Insulation failure, winding to tank | `insulation_tank` injection, alert `earth_leakage` (tank earth current) |
| Thermal lag | oil and winding time constants on the condition card; the Thermal lag layer |
| Charging current, idle conductors | `charging_current` injection, alert `charging_current` (leading kVAr at low load) |
| Temperature increase alarm | alert `temp_rise_fast` (K/h), OTI/WTI alarm and trip settings |
| ±6 % voltage | alerts `voltage_high`, `voltage_low` |
| Life of transformer | condition card and report: insulation life left, years at the present ageing rate |
| Silica gel colour | condition card; scale is cobalt-chloride gel: **blue dry, pink saturated**. Replace at about two thirds saturated |
| Moisture levels | `moisture_ingress` injection, alert `moisture_high` (20 ppm watch, 30 ppm action) |
| Efficiency monitoring | `eta_pct` against `eta_ref_pct` from the nameplate losses, alert `efficiency_low` |

The silica-gel colours in your note were the reverse (blue as degraded, pink as good). The usual cobalt-chloride gel is blue when dry and turns pink when it has taken up water, so the
board uses that. If your breather uses another indicator, change `SILICA_COLOURS` in `twin/condition.py`.

## Report with a snapshot

**Export, Report (PDF with snapshot)** takes a picture of the 3D twin in the browser and sends it to `POST /api/datasets/{id}/report.pdf`; the PDF has the snapshot, the status, the
condition table against the limits, the last seven days, recent alerts and the outlook. `GET /api/datasets/live/report.pdf` is not provided: the picture only exists in the browser.

## Blueprint kit

**Export, Blueprint kit** (`GET /api/blueprint.zip`) gives engineers: a PDF of drawings and schedules, the drawings as SVG, the sensor and terminal schedules as CSV, `asset.yaml`,
`thresholds_india.yaml`, a gateway script for CSV or Modbus readings, and `README_INSTALL.md`. The general arrangement is schematic (no dimensions); take dimensions from the
manufacturer's drawing. The Modbus mode of the gateway has not been run against hardware.

## Limits

- The three condition columns (`H2O_ppm`, `SILICA_pct`, `IEARTH_A`) and `eta_pct` exist for the simulated plant. A real device feed needs them mapped in `config/synonyms.yaml`.
- Isolation Forest and Prophet on the live source have less history (about two weeks at most) than on the replay datasets.
- Faults are fast-forwarded to a demo timescale.
