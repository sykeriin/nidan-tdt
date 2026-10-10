# Bindings: visual property → backend field

The frontend computes no engineering values. Every number and every data-driven visual property below comes from
the FastAPI backend (`docs/API.md`). Pure presentation (layout, time → pixel position on the ruler, trust badge from
`dq_flags`) is listed as such.

Endpoints used: `GET /api/datasets` (D), `GET /api/datasets/{id}/run?max_points=10` (R),
`GET /api/datasets/{id}/frames` (F, the whole run as columns, loaded once and replayed client-side by `player/player.ts`),
`GET /api/datasets/{id}/thermal-profile` (P, model constants only, fetched once),
`GET /api/datasets/{id}/components?t=` (C, at the cursor, only while a part is pinned).
In Mirror mode every `row.*` / `twin.*` / `health.*` value below is read from F at the replay cursor
(health columns arrive prefixed `health_`). The replay clock picks a row index; it never interpolates values.

## Model (3D)

| Visual property | Driven by | Endpoint |
|---|---|---|
| Oil column height in the conservator glass gauge | `row.OLI_pct` / 100 | S |
| Part highlight (blueprint wash) | user hover / pin (UI state) | — |
| Tank section A–A (front half removed) | user toggle (UI state) | — |

| Oil heat colour (inferno, 20–140 °C) | `OTI_C`; `twin_oil_C` when OTI is missing or suspect | F |
| Winding heat colour, all three limbs | `hs_ageing_C`, else `twin_hs_C` | F |
| Twin ghost (blueprint outline of the windings) | always drawn; dashed when `fidelity_alert` is true | F |
| Hot-spot marker position | limb of the phase with the largest of `IR, IY, IB` (an argmax picks the limb; no value is computed) | F |
| Hot-spot marker text | `hs_ageing_C` (source from `ageing_source`: "measured oil + gradient" or "estimated by twin"), `twin_hs_C` | F |
| Residual tag at the oil surface | `OTI_C` vs `twin_oil_C`, `residual_oil_C`; drift line when `fidelity_alert`; becomes the "sensor suspect" tag when OTI is suspect; meter_only shows twin only | F |

| Oil particles (300, instanced) | path is drawn geometry; speed ∝ `oil_flow_intensity` (est.); colour: `bottom_oil_C` at the bottom, top-oil (as the oil colour) at the top; radiator outlet colour = top → bottom blended by `radiator_effectiveness` (est.) | F |
| Heat-flow arrows, width ∝ W, label name + kW | core: `losses_noload_W`; windings: `losses_load_W`; to air: `heat_dissipated_W` (all est.); one width scale per run from `params.P0_W + params.Pk_W` | F, P |
| Tank see-through (glass) | tank hovered or pinned (UI state); shows the oil colour and circulation inside a closed tank | — |
| Detail bubble (lettered circle) on a pinned part | pinned state (UI) | — |

Toggle: every row above belongs to a physics layer (Schedule 3, `twin/layers.ts`).

## Heat balance (field, bottom right; hidden while a detail view is open)

| Row | Field |
|---|---|
| core, windings, heat in | `losses_noload_W`, `losses_load_W`, `losses_total_W` |
| to air, stored | `heat_dissipated_W`, `heat_stored_W` (sign → heating up / cooling down / steady) |

## Life clock (right margin)

| Element | Field |
|---|---|
| Hands (1 turn = 1 day of paper life) | blue `days_aged_cum` (expected); vermilion `days_aged_actual_cum` (actual, hidden in meter_only) |
| Ageing rate, expected / actual | `aging_rate`, `aging_rate_actual` |
| Life used, expected / actual | `days_aged_cum`, `days_aged_actual_cum` |

## Section thermometer (field, top left) — IEC 60076-7 thermal diagram

| Element | Field |
|---|---|
| Oil line, bottom → top | `bottom_oil_C` (est.) → `twin_oil_C` |
| Winding line (parallel to the oil line) | through `avg_winding_C` (est.) at mid-height |
| Hot-spot point, gradient dimension | `twin_hs_C`; dimension label `hs_gradient_K` |
| Measured marks (vermilion) | `OTI_C` (hidden if suspect / meter_only), `hs_ageing_C` when `ageing_source == "measured"` |
| Ambient line | `amb_C` |

## Thermal lag (left margin, last 18 h)

| Trace | Field |
|---|---|
| Load K (step) | `load_pu` |
| Hot-spot / top-oil (solid) | `twin_hs_C` / `twin_oil_C` |
| Steady-state targets (dashed) | `hot_spot_ss_C` / `top_oil_ss_C` |
| τ dimension | `tau_oil_min`, `tau_winding_min` (length on the time axis is presentation) |

## Detail views (pinned parts, field right)

| Element | Field |
|---|---|
| Quantities (label, value, unit, kind, est.) | `C.parts[id].quantities[]` |
| Mini time-history (3 days) | the same `key` in F, when present |
| Equation, symbolic and with live values | `C.parts[id].equations[].symbolic`, `.substituted`, `.result`, `.terms[]`, `.note` |
| Findings, last 24 h | `C.parts[id].alerts[]` (severity, origin, explanation) |
| Recommended test | `C.parts[id].tests[]` |

## Heat scale (field, left)

| Mark | Field |
|---|---|
| ambient | `amb_C` |
| top-oil twin / measured | `twin_oil_C` / `OTI_C` (hidden when meter_only or suspect) |
| hot-spot twin / measured | `twin_hs_C` / `hs_ageing_C` |
| hatched gap + dimension | between `OTI_C` and `twin_oil_C`, labelled `residual_oil_C` |

## Timeline (strip, bottom)

| Element | Field |
|---|---|
| Measured / twin traces | `OTI_C`, `twin_oil_C` (per-pixel min/max decimation for drawing only) |
| "fault injected" flag | first row where `gt_fault == 1` (simulated scenarios only) |
| Alert marks | `R.analysis.alerts[]`: `timestamp`, `severity` (filled when critical), `origin` (square = sensor) |
| Through-fault marks | `R.events.rows[]`: `timestamp`, `peak_pu`, `duration_ms` |
| Cursor, time readout | replay clock → nearest row of F |

## Callouts (hover / pin)

Defined in `parts.ts`. Each row is `{source, key}`: `row.*` and `twin.*` from S, `asset.*` from R.

| Part | Fields |
|---|---|
| Tank, insulating oil, top-oil pocket | `row.OTI_C` (measured), `twin.twin_oil_C` (twin), `twin.residual_oil_C` |
| Core | `asset.no_load_loss_W` (est.: placeholder nameplate), `twin.load_pu` |
| Winding R / Y / B | `row.IR`/`IY`/`IB`, `twin.twin_hs_C`, `row.WTI_C`, `twin.aging_rate_actual` |
| Radiator bank | `row.amb_C`, `twin.twin_oil_C` |
| Conservator, oil-level gauge | `row.OLI_pct` |
| Breather | `row.RH_pct` |
| HV bushings | none: not measured (note) |
| LV bushing R / Y / B | `row.VR`/`VY`/`VB`, `row.IR`/`IY`/`IB` |
| LV neutral bushing | `row.IN` |
| LV current transformers | `row.IR`, `row.IY`, `row.IB` |
| Ambient sensor | `row.ATI_C`, `row.amb_C` |
| Nameplate | `asset.rating_kVA`, `asset.lv_voltage_V`, `asset.i_rated_A`, `asset.load_loss_W` (est.) |

Trust badge (presentation of backend flags, `data/fields.ts`):
- **missing:** the value is null.
- **suspect:** `row.dq_flags` holds a fault code for that channel (RANGE/JUMP/STUCK/NEG, IMPLAUSIBLE_RISE,
  ATI_MISMATCH), or, for OTI, `run.summary.plausibility.OTI_C == "suspect"`.
- **est.:** a provenance code (IMPUTED/DERIVED/ASSUMED).
- **trusted:** none of the above.

## Schedules

| Schedule row | Field |
|---|---|
| Data in | `row.OTI_C, WTI_C, ATI_C, IR, IY, IB, IN, VR, VY, VB, PF, freq_Hz, OLI_pct, RH_pct` + trust badge |
| Twin state | `twin.load_pu, losses_total_W (est.), heat_dissipated_W (est.), bottom_oil_C (est.), twin_oil_C, twin_hs_C, residual_oil_C, fidelity_rmse_C` (ageing and life used are on the life clock); residual struck through and badged suspect when OTI is suspect |
| Health index | `health.score`, `health.band` (stamp colour), `health.components.*` (sub-score rows and bars) |

## Sheet

| Element | Field |
|---|---|
| Dataset name | `D[].name` |
| Import ("Load file") | `POST /api/datasets` (multipart `files`, `name`, `asset=estimate` when *other transformer*); D is refetched and the sheet switches to the returned `dataset_id` |
| SIMULATED stamp | `D[].simulated` (fallback `S.simulated`) |
| Title block: rating line | `asset.rating_kVA`, `asset.hv_voltage_V`, `asset.lv_voltage_V`, `asset.cooling` (absent fields omitted); "(estimated from data)" when `asset.nameplate_source == "estimated"` |
| Title block: mode | `run.mode` |
| Title block: time | `F.timestamp[i]` |
| Ruler extent | `D[].start`, `D[].end` (time → pixel is presentation) |

Colour key: measured values vermilion `#D9480F`, twin values blueprint `#2457A6`, residual ink double-underlined.
Health colours only in the health stamp.
