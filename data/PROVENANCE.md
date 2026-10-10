# Data provenance

Owner: P1 (Data). Every number below was produced by code in this repo; nothing was typed in by hand.
Raw files are never modified. Cleaning lives in `ingest/` + `config/schema/kaggle.yaml`; rerun with
`python -m ingest.kaggle_clean` (full health report: `data/clean/kaggle_health_report.json`).

---

## 1. Kaggle — "Distributed Transformer Monitoring" (real field data, different transformer)

- **Source:** kaggle.com/datasets/sreshta140/ai-transformer-monitoring [Confirmed]
- **Acquired:** 2026-10-10 (file timestamps inside `dt-data.zip`; entered the repo in commit `ca9f862`,
  extracted in `be66cb2`). The original Kaggle download date and dataset version were not recorded. **[Open]**
- **Use:** Real Field Data page, adapter fixture F2, sensor-vs-asset demo, physics plausibility check (PRD §7.4). **Never** used to
  calibrate Transformer-1. Device alarm flags are display-only, never ML features/targets.

### 1.1 Files (raw, unmodified)

| File | SHA-256 | Bytes | Rows | Columns |
|---|---|---|---|---|
| CurrentVoltage.csv | `885fad08ecc4fd631a8ab483573796f0ca0dbcddbb6d252d7c2b23cc9b18eae7` | 1,428,576 | 19,352 | VL1–3, IL1–3, VL12, VL23, VL31, INUT |
| Overview.csv | `99c371db6d8fb73669ab5036e1cdaae93a8f590dfb0bc1301807cfc415888be7` | 1,003,649 | 20,316 | OTI, WTI, ATI, OLI, OTI_A, OTI_T, MOG_A |
| Power.csv | `f1aa074386c9d7e72b06105f8732d168e57227c240f70f7985563aced53b0128` | 1,183,477 | 19,309 | WL1–3, VAL1–3, RVAL1–3 |
| PowerFactor.csv | `cc36cec106b1be03a13d62da5d6b5d0fe24da9a140817f0ceac1ea715f0e39a7` | 1,739,626 | 19,308 | PFL1–3, Avg_PF, Sum_PF, FRQ, THDVL1–3, THDIL1–3, MDIL1–3 |
| TotalPower.csv | `0e1995281f5857435be846ff0716151eca044f5c4362b16064c16e947046b623` | 1,560,439 | 19,248 | KWH, KWH_I, KVARH, KW, KVA, KVAR, MPD, MKVAD |

All files: timestamp column `DeviceTimeStamp`, ISO 8601 without timezone (assumed Asia/Kolkata — the
daily load peak at 18–19 h matches an Indian evening peak in local time). **No missing values (NaN) in any file.**

### 1.2 Per-file inspection (whole file, before range selection)

| File | Date range | Median interval | Unique timestamps | Duplicate-ts groups | of which identical | of which conflicting | All-zero rows |
|---|---|---|---|---|---|---|---|
| CurrentVoltage | 2019-06-25 13:06 → 2020-04-14 00:30 | 15 min | 18,915 | 437 | 32 | **405** | 3 |
| Overview | 2019-06-25 13:06 → 2020-04-14 00:30 | 15 min | 19,376 | 931 | 568 | **363** | 0 |
| Power | 2019-06-25 13:06 → 2020-04-14 00:30 | 15 min | 18,871 | 438 | 429 | 9 | 1,707 |
| PowerFactor | 2019-06-25 12:39 → 2020-04-14 00:30 | 15 min | 18,877 | 431 | 1 | **430** | 5 |
| TotalPower | 2019-06-27 10:51 → 2020-04-14 00:30 | 15 min | 18,842 | 406 | 393 | 13 | 2 |

Overview's 931 groups / 363 conflicting matches the public audit (`MohamedMehery/transformer-telemetry-integrity-audit`) exactly. [Reported → Confirmed]

**Value ranges (min / p1 / median / p99 / max)** — selected; full table in the inspection log:

| Column | min | p1 | median | p99 | max | Note |
|---|---|---|---|---|---|---|
| VL1/VL2/VL3 (V, L-N) | 0 | ~220 | ~242 | ~255 | 261 | 0 = meter offline |
| VL12/23/31 (V, L-L) | 0 | 0 | ~417 | ~443 | 447 | |
| IL1 / IL2 / IL3 (A) | 0 | 0 | 69.5 / 50.2 / 80.2 | 175 / 167 / 182 | 224 / 254 / 247 | |
| INUT (A) | 0 | 0 | 25.6 | 64.8 | 145.8 | |
| OTI (°C) | 0 | 15 | 29 | 48 | **250** | 245–250 °C glitches |
| **WTI** | 0 | 0 | 0 | 1 | 1 | **0/1 only — a flag, not a temperature** |
| ATI (°C) | 0 | 14 | 28 | 41 | 44 | |
| OLI (%) | 36 | 39 | 73 | 100 | 100 | |
| OTI_A / OTI_T / MOG_A | 0 | 0 | 0 | 0 / 0 / 1 | 1 | 100 / 47 / 2,087 rows set |
| KW / KVA | −0.84 / 0 | 0 | 47.5 / 48.2 | 112.9 / 113.6 | 142.2 / 142.9 | |
| Avg_PF | −0.96 | 0.95 | 0.98 | 1.0 | 1.0 | |
| FRQ (Hz) | 0 | 49.8 | 50.0 | 50.1 | 50.2 | |
| KWH_I | −54.5 | 0 | 11.7 | 28.9 | **33,000.5** | spike = energy accumulated over the 33-day gap |
| Sum_PF | −164.4 | −90.4 | 10.1 | 17.7 | 35.2 | meaning unclear; kept as `extra_sum_pf` |

Units check: meter KVA ÷ Σ(V·I)/1000 = 0.99 (median) and Σ VAL = KVA → currents are amps, voltages are volts.

### 1.3 Alignment across files

- Union of timestamps: 20,024; present in **all five** files: 18,324 (91.5 %).
- Each file sits on the :00/:15/:30/:45 grid. Off-grid timestamps (e.g. :16, :44, :46) appear after outages, and
  the same restart is logged a minute apart in different files (e.g. 14:38 vs 14:39), so those rows don't line up.
- Merged on exact timestamp (spec: outer join). In the chosen range, **970** rows have no CurrentVoltage values
  and **584** have no Overview values. They are kept; downstream treats the missing channels as NaN.

### 1.4 Specific checks

**(1) OTI/WTI jumps > 5 °C per 15 min.** Rule used: |ΔOTI| scaled to max(Δt, 15 min), not across gaps.
- OTI: **47** jumps in the whole file, **43** in the chosen range (Jul 12, Aug 25, Sep 6). The 1-minute
  sampling bursts in June/July give 212 "jumps" if you scale a 1 °C step over 1 min to 15 min, but those are
  sensor resolution, not jumps. The rule above avoids that.
- Glitch types: plateaus at **236–250 °C** on 8 afternoons (2019-07-16, 08-09, 08-16, 08-17, 08-18, 08-19,
  08-22, 09-03; 47 rows in range), and drops to **0 °C** (12 rows in range) together with ATI = 0.
- **WTI is not a temperature** (values 0/1; 17 rows at 0.5 come only from median-merged duplicates). No WTI jump
  check is possible. It is mapped to `alarm_WTI`, display only. It is 1 more often at night and at low load
  (median loading 25 % when 1 vs 37 % when 0), so it is not an over-temperature alarm either. Meaning unknown. **[Open]**

**(2) Does MOG_A = 1 coincide with OLI dropping? No.**
- MOG_A = 1 on 2,087 rows, all between 2019-07-02 and 2019-08-10, always while OLI is 38–41 %.
- At each of the 5 rising edges, OLI 6 h before vs 6 h after changed by **+0.2** points on average: no drop.
- OLI ≤ 41 % on 4,421 rows in range; MOG_A was set on only 2,087 of them and went silent on 2019-08-10 although
  the level stayed ≤ 41 % until mid-September.
- Correlation(MOG_A, OLI) = −0.41, driven entirely by "MOG_A only fires while the level is low".
- **Reading:** MOG_A behaves like a low-level *state* alarm that was later disabled or reset — not a leak event.

**(3) One continuous transformer, or breaks/regime changes? One asset, with gaps and two regime changes.**
- **Same asset throughout.** Across every logging gap from 2019-07-25 on (including 33 days, 2019-12-15 →
  2020-01-17, and 14 days, 2020-03-07 → 03-21), the cumulative energy counter KWH advanced by an amount equal
  to 38–75 kW average load — consistent with the 48 kW median. The meter kept counting through the outages, so
  they are logger/communication gaps, not a swapped meter or asset. KWH never resets (one transient 0 reading).
- **Gaps:** 17–19 gaps > 1 day per file; largest 33.6 d, 14.6 d, 7.6 d, then several of 4–5 d.
- **Regime change A — before 2019-07-01:** zero current on every row (907 rows in June), OTI ≈ ATI, KWH frozen
  at 54.5. Not energised / CTs not connected.
- **Regime change B — oil level:** OLI climbs **gradually** from ~40 % to 100 % between 2019-09-26 and
  2019-11-17 (seven weeks, with daily swings). It is not a refill (that would be a step), so most likely sensor
  drift. From December it reads exactly 100 on **99.4 %** of rows (7,188 / 7,234) — saturated/stuck.
- **Regime change C — from 2020-03-25:** evening (17–20 h) median current falls from 107 A to 72 A and p95 from
  114 A to 79 A, against ~equal median. The date coincides with India's national lockdown. [Reported context]
- Seasonal, not a break: load highest Aug–Sep, lowest Dec–Feb; L-N voltage rises from ~233 V to ~246 V in November.
- Thermal: **OTI − ambient is small** (median 2 K, p99 10 K) for a unit loaded at ~34 % median. This fails the
  physics plausibility check (§1.8): the OTI channel can't be reading top-oil.

### 1.5 Estimated rating (no nameplate)

Spec rule (§2.7): I_rated = p99(I_mean) / 0.8.
- Whole file: p99 I_mean 169.3 A → **212 A ≈ 152 kVA** at 415 V.
- Chosen range (what the cleaned file uses): **214.7 A ≈ 155 kVA** at the measured 417.5 V L-L.
- Cross-checks: max phase current 254 A, max-demand current (MDIL) 235 A, max KVA 143, max-demand kVA 136.
  Nearest standard Indian DT ratings are 160 kVA (223 A) or 200 kVA (278 A). The max-demand registers fit
  either, so we keep the data estimate.
- Tag: **[Assumed — estimated from data]**. Loading on this unit is relative to this estimate, not a nameplate.

### 1.6 Decisions

**Date range: 2019-07-01 00:00 → 2020-03-24 23:59 (Asia/Kolkata).**
- Start: drop June 2019 (not energised; no current on any row).
- End: drop 2020-03-25 onwards (load regime change C, only 20 days, after a 14-day gap). It would bias the
  9-month record with a second load regime.
- Keep the logging gaps inside the range. They are flagged `GAP`, and the twin restarts from steady state after
  a long gap (PRD §7). Splitting into segments would throw away most of the OTI glitches we need for the
  sensor-fault demo (Jul–Sep).
- Keep the OLI regime change (B) inside the range. It is flagged `STUCK_OLI` where saturated, and OLI isn't
  used by the twin.

**What the MOG_A result changes.**
1. The PRD rule stands and is now evidenced: MOG_A is an oil-gauge *state* alarm, not a leak label.
2. **There are no usable leak or theft events in the Kaggle data.** OLI never drops at an alarm; it rises and
   then saturates. The leak-vs-theft detector can only be demonstrated and evaluated on generated S4a/S4b.
3. On the Real Field Data page, the oil module should show data quality (drift, stuck at 100 %, alarm
   disabled after 08-10), not leak alerts. The capability matrix still reports `oil_leak_theft: true`
   because OLI is present. P3 should gate on `STUCK_OLI`.
4. MOG_A Jul–Aug is the only window where a device alarm can be compared with our own classification.

### 1.7 Cleaning (adapter, `config/schema/kaggle.yaml`) — counts

Pipeline: read → parse time (ISO, tz Asia/Kolkata) → map to canonical R/Y/B names → dedupe **per file**
(identical → keep one, `DUP_IDENT`; conflicting → numeric median, alarm flags max, `DUP_CONFLICT`) → outer
merge on timestamp → range filter → derive → validate → enrich ambient → loading %.
**No row is deleted;** every flag stays on the row.

| Step | Count |
|---|---|
| Rows read (5 files) | 19,352 + 20,316 + 19,309 + 19,308 + 19,248 = 97,533 |
| After per-file dedupe | 18,915 + 19,376 + 18,871 + 18,877 + 18,842 |
| After outer merge (all dates) | 20,024 (18,324 present in all files) |
| **In chosen range → `data/clean/kaggle.parquet`** | **17,104 rows × 56 columns**, 2019-07-01 11:10 → 2020-03-24 23:45 |
| Median interval | 15 min |

**dq_flags in the cleaned file (rows):**

| Flag | Rows | Meaning |
|---|---|---|
| DUP_CONFLICT | 348 | conflicting duplicates, median kept |
| DUP_IDENT | 124 | identical duplicates, one kept |
| GAP | 57 | spacing > 3 × interval before this row |
| JUMP_OTI | 43 | OTI change > 5 °C / 15 min |
| RANGE_OTI_C | 59 | 47 at 236–250 °C, 12 at 0 °C (dropout) |
| RANGE_ATI_C | 10 | ATI 0 °C dropouts |
| RANGE_VR / VY / VB | 2 / 9 / 4 | L-N voltage < 100 V (meter offline) |
| RANGE_freq_Hz | 2 | FRQ = 0 |
| STUCK_OTI | 770 | OTI flat ≥ 8 samples while load moves > 10 %. Partly 1 °C sensor resolution on a lightly loaded unit |
| STUCK_OLI | 8,731 | OLI saturated at 100 % |
| STUCK_IY / STUCK_IB | 14 / 14 | |
| IMPUTED_AMB | 594 | amb_C from Open-Meteo Hyderabad where ATI is missing/invalid |
| IMPUTED_RH | 17,104 | RH from Open-Meteo Hyderabad (no RH sensor) |
| ATI_MISMATCH | 57 | ATI vs Open-Meteo > 8 °C for > 6 h (§1.8) |
| IMPLAUSIBLE_RISE | 13,618 | OTI − ambient outside the IEC band (§1.8) |
| DERIVED_loading_pct | 16,134 | loading = I_mean / estimated I_rated |

- Rows with ≥ 1 *quality* flag (not DERIVED/IMPUTED/ASSUMED), before the plausibility flags: 9,630; excluding STUCK_OLI: **1,345**.
- No NEG flags (no negative currents or kVA).
- Missing channels from the merge: 970 rows without currents/voltages, 584 without OTI/ATI/OLI.

**Mapping.** IL1/2/3 → IR/IY/IB · VL1/2/3 → VR/VY/VB · VL12/23/31 → VRY/VYB/VBR · INUT → IN · KVA → S_kVA ·
KW → P_kW · KVAR → Q_kVAr · Avg_PF → PF · FRQ → freq_Hz · OTI → OTI_C · ATI → ATI_C · OLI → OLI_pct ·
WTI/OTI_A/OTI_T/MOG_A → `alarm_*` · everything else → `extra_*`. `source = kaggle_real`, `simulated = False`.

**Capabilities / mode:** full (OTI present). Unbalance, voltage quality, measured neutral, ageing on.
No WTI temperature, no event log (through-fault off), no RH (breathing off), no ground truth.

**Auto-map check (no schema):** the adapter maps the same files the same way without the YAML, and rejects WTI
as a temperature because its values are binary.

### 1.8 Physics plausibility check (`twin/plausibility.py`, PRD §7.4)

Run on the cleaned file at the estimated 214.7 A rating. Plot: `docs/figures/kaggle_plausibility.png`.

| Channel | Verdict | Evidence |
|---|---|---|
| **OTI_C** | **suspect** | Measured OTI − ATI median **2.0 K** at median load 0.34 pu. IEC 60076-7 band at the same load: low 9.1 K · nominal 20.9 K · high 27.5 K. **13,618 of 15,628** evaluable rows (87 %) are > 2 K below the low edge; 0 above. Against Open-Meteo air temperature instead of ATI, the median rise is 4.2 K and 73 % of rows are still below. Core losses alone hold ≥ 4.4 K at zero load (low band). A larger nameplate doesn't rescue it: at 5× the rating the low band still predicts 4.6 K. |
| **ATI_C** | **plausible** | vs Open-Meteo Hyderabad: bias +2.27 °C, MAE 3.49 °C, correlation 0.74 (15-min) / 0.63 (daily). Peak at the same hour (lag 0), which supports IST timestamps. Diurnal swing is 13 K vs 7 K for air, so the sensor runs ~5 K hot at noon (sun/enclosure). `ATI_MISMATCH` on 57 rows. |

- **Location:** Hyderabad is **[Assumed]**. Evidence: ATI correlates with Hyderabad weather at 0.63 (daily means)
  against 0.27 for Bengaluru over the same dates (Bengaluru fetched to scratch for this comparison, not cached).
- Evaluable rows exclude RANGE_OTI_C / RANGE_ATI_C / JUMP_OTI / STUCK_OTI (already sensor faults) and rows without load.
- Flags written to `kaggle.parquet`: `IMPLAUSIBLE_RISE` 13,618 rows, `ATI_MISMATCH` 57 rows.
- With the Hyderabad cache in place, the 594 rows without ATI get ambient from Open-Meteo (`IMPUTED_AMB`) instead of
  interpolation/climatology, and RH comes from the cache (`IMPUTED_RH`). There are no `ASSUMED_AMBIENT` rows any more.

---

## 2. Open-Meteo — Bengaluru hourly temperature and RH

- Archive API `archive-api.open-meteo.com/v1/archive`, request point 12.9716 N, 77.5946 E; the API snapped it
  to 12.970 N, 77.564 E, elevation 910 m. `timezone=Asia/Kolkata`.
- April 2026: 720 hourly rows, 0 nulls, temperature 19.9–36.9 °C, RH 14–92 %.
- Hyderabad (Kaggle unit, [Assumed location]): 17.385 N, 78.487 E, Jul 2019 – Mar 2020, cached as
  `data/cache/weather/hyderabad_YYYY-MM.json` (fetched 2026-10-10).
- Cache: `data/cache/weather/bengaluru_2026-04.json` (fetched 2026-10-10 with `python -m ingest.enrich fetch 2026 4`).
  It is byte-identical in values to `data/raw/weather/bengaluru_2026-04_raw.json` (max |Δ| = 0).
- Everything downstream reads the cache only; tests run with the network blocked.
- License: Open-Meteo data is CC BY 4.0; cite Open-Meteo.

## 3. Generated campus data (Transformer-1) — SIMULATED

- `python -m sim.generator` writes `data/generated/trend_<ID>.csv`, `events_<ID>.csv`, `meta_<ID>.json` for
  N, S1, S2, S3, S4a, S4b, S5. Seed 0. April 2026, 15 min, 2,880 rows each. Canonical format, `source = generated_sim`,
  `simulated = True`, ground truth in `gt_fault` / `gt_type` only.
- Plant parameters (seed 0): top-oil rise × 0.9647 (57.9 K), hot-spot factor 1.1802. The twin keeps nominal
  values (60 K, 1.2). The mismatch is deliberate (PRD §5.1).
- Magnitudes are in `config/scenarios.yaml`. Plots are in `docs/figures/scenario_<ID>.png`.

## 4. ETT (zhouhaoyi/ETDataset)

- `data/raw/ett/ETTh1.csv`, `ETTh2.csv`, `ETTm1.csv`, `ETTm2.csv`, not used yet. The repo LICENSE reads CC BY-ND 4.0:
  validation only, no modified copies, cite Zhou et al. AAAI 2021.

## 5. Organizers' files (reference only)

- `Draft Data for Condition Monitoring.xlsx` (repo root) is a device acceptance test, not time-series data.
  It confirms R/Y/B naming, L-N voltages around 259 V on the rig, ≤ 1 % accuracy, and 50 A / 60 °C trips — the
  self-test panel only (PRD §3.2).
