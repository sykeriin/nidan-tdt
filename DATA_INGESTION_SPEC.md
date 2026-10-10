# DATA INGESTION SPEC — "Any Data In"

Companion to `FINAL_PRD.md`. Owner: **P1 (Data Lead)**. Status: final.

---

## 0. Why this exists

The problem PDF says the solution **"should work with simulated datasets provided during the hackathon"** and **"be designed so that it can be extended later to connect with real sensors and utility monitoring systems."**

We don't know the organizers' format in advance. So the twin never reads raw files directly. Everything passes through one adapter that turns whatever arrives into the canonical tables, tells the rest of the system what it can and can't compute, and degrades gracefully instead of crashing.

**Design rule:** *If a column can't be mapped, a feature turns off — the app never breaks.*

**Finale target:** organizers' file → mapped, validated and running in the dashboard in **≤ 15 minutes**, ideally 2.

---

## 1. Pipeline

```
 file(s) / stream
      │
      ▼
 1. READ        format detection: CSV/TSV, XLSX/XLS (all sheets), JSON/JSONL, Parquet, ZIP of these
      │
      ▼
 2. SHAPE       wide vs long (tag/value historian) → pivot to wide; multi-file merge on time;
                multi-asset → select transformer_id
      │
      ▼
 3. TIME        find & parse timestamp (formats, epoch, split date/time, DD/MM Indian), tz, sort,
                dedupe, detect interval
      │
      ▼
 4. MAP         auto-propose column → canonical mapping (synonyms + units + value ranges),
                confidence score; user confirms/edits in UI; save as schema YAML
      │
      ▼
 5. UNITS       convert to canonical units (kA→A, kV→V, °F/K→°C, L-L→L-N, %, fractions→%)
      │
      ▼
 6. DERIVE      fill derivable channels (S from V&I, per-phase from total, amps from loading %)
                — every derived value flagged
      │
      ▼
 7. ENRICH      ambient/humidity from Open-Meteo cache if missing; nameplate from file/UI/defaults
      │
      ▼
 8. VALIDATE    range checks, gaps, stuck sensors, impossible jumps → dq_flags
      │
      ▼
 9. CAPABILITIES  compute capability matrix → which modules run, which mode
      │
      ▼
 canonical trend table + event table + Data Health Report
```

Same mapping is applied **row by row** for streaming/replay (`map_row(dict) -> dict`), so a real sensor feed later uses the identical code path.

---

## 2. Step details

### 2.1 READ

| Input | Handling |
|---|---|
| `.csv`, `.tsv`, `.txt` | Sniff delimiter (`,` `;` `\t` `|`), encoding (utf-8, utf-8-sig, latin-1), skip leading metadata rows until a row looks like a header |
| `.xlsx`, `.xls` | Read **all sheets**; each sheet scored as trend / events / nameplate / other (2.2) |
| `.json`, `.jsonl` | Records → DataFrame; nested dicts flattened with `_` |
| `.parquet` | Direct |
| `.zip` | List, read each supported file inside |
| Multiple files | Each read separately, then merged (2.2) |

Large files: read in chunks when > 200 MB.

### 2.2 SHAPE

**Sheet/file role classification** (heuristic score, user can override):

| Role | Signals |
|---|---|
| **trend** | A timestamp column with regular spacing; many numeric columns |
| **events** | Sparse irregular timestamps; columns like `event`, `fault`, `trip`, `peak`, `duration`, `ms` |
| **nameplate** | Few rows; keys like `kVA`, `rating`, `impedance`, `losses`, `vector` |
| **other** | Ignored but listed in the Data Health Report |

**Long (historian) format** — detected when columns look like `timestamp, tag/name/parameter, value`: pivot to wide with one column per tag, then map tags like columns.

**Multi-file merge** — outer join on timestamp after each file's time is normalized; conflicts between files flagged `MERGE_CONFLICT`.

**Multiple transformers** — a column like `transformer_id`, `dt_id`, `asset`, `tag prefix TR1_/TR2_` → UI dropdown to select one asset (fleet view is out of scope).

### 2.3 TIME

- Candidate columns by name (`time`, `timestamp`, `date`, `datetime`, `DeviceTimeStamp`, `ts`) and by parse success rate.
- Supported: ISO 8601; `DD/MM/YYYY HH:MM[:SS]` (**default day-first — Indian convention**; switch to month-first only if day-first produces invalid dates); `MM/DD/YYYY`; Excel serial dates; epoch seconds / milliseconds (detected by magnitude); separate `date` + `time` columns combined.
- Timezone: assume `Asia/Kolkata` if naive; convert if offset given.
- Sort ascending; duplicates → `DUP_IDENT` (identical, keep one) or `DUP_CONFLICT` (median of numeric values, flagged).
- **Interval detection:** median spacing. Canonical interval = native interval, kept as is (the thermal library takes a datetime index).
  - < 1 min → resample to 1 min (mean for analog, max for currents also kept as `*_max` for event detection, max for alarm flags).
  - 1–60 min → keep.
  - > 60 min → keep but warn: "coarse data, thermal dynamics under-resolved."
- Gaps > 3× interval → `GAP` flag; not interpolated across for the twin (twin restarts from steady state after a long gap, flagged).

### 2.4 MAP — auto-mapping with synonyms

Header normalization: lowercase, strip units in brackets/parentheses (kept for 2.5), replace separators with `_`.

**Synonym dictionary** (`config/synonyms.yaml`, extendable on the day):

| Canonical | Matches (examples) |
|---|---|
| `IR` | ir, i_r, ia, i_a, il1, i1, current_r, r_current, phase_r_current, curr_r, amp_r, r_phase_amps |
| `IY` | iy, i_y, ib*, i_b*, il2, i2, current_y, y_current |
| `IB` | ib, i_b, ic, i_c, il3, i3, current_b, b_current |
| `IN` | in, i_n, inut, neutral, neutral_current, i0 |
| `VR`/`VY`/`VB` | vr, v_r, va, vl1, v1, vrn, van, voltage_r … (phase–neutral) |
| `VRY`/`VYB`/`VBR` | vry, vab, vl12, v12, vll, line_voltage … (line–line) |
| `I_total` | current, load_current, i, amps, total_current |
| `S_kVA` | kva, apparent_power, s |
| `P_kW` | kw, active_power, p, real_power |
| `Q_kVAr` | kvar, reactive_power, q |
| `PF` | pf, power_factor, cos_phi |
| `freq_Hz` | f, freq, frequency, hz |
| `loading_pct` | loading, load_pct, load_percent, percent_load, utilization |
| `OTI_C` | oti, top_oil, oil_temp, oil_temperature, tot |
| `WTI_C` | wti, winding_temp, winding_temperature, hst, hot_spot* |
| `ATI_C` | ati, ambient, amb_temp, ambient_temperature, outdoor_temp |
| `OLI_pct` | oli, oil_level, level, conservator_level |
| `RH_pct` | rh, humidity, relative_humidity |
| alarm flags | oti_a, oti_t, mog_a, *_alarm, *_trip, buchholz, prv |
| ground truth | fault, label, fault_type, class, anomaly, status_label, is_fault |
| `transformer_id` | transformer_id, dt_id, asset, tr_no |

\* `ib` is ambiguous (Y-phase in A/B/C naming vs B-phase in R/Y/B). Resolved by context: if `ia`/`ic` exist → A/B/C scheme (A→R, B→Y, C→B); if `ir`/`iy` exist → R/Y/B.

**Scoring** each candidate = name match (exact > synonym > fuzzy) + unit hint agreement + value-range plausibility (e.g., temperatures 0–150, voltages 180–270 L-N or 330–470 L-L, PF 0–1 or 0–100). Proposal shown with confidence; anything < 0.6 left unmapped for the user.

**UI ("Data Import" page):** table of source columns → dropdown of canonical names with the proposal preselected, a 10-row preview, detected units, and **Save mapping** → `config/schema/<name>.yaml`. Re-loading the same source applies the saved mapping instantly.

**Hard rules:**
- **Ground-truth columns** (fault labels) are quarantined to `gt_*`, used only by `eval/`, never by detectors.
- **Device alarm flags** are kept for display and comparison, never as ML targets or features.
- Unmapped numeric columns kept as `extra_<name>` and viewable on the Raw Data tab.

### 2.5 UNITS

| Quantity | Detect | Convert to |
|---|---|---|
| Current | header `kA`, or magnitudes ≪ expected | A |
| Voltage | header `kV`; magnitude ~0.4 → kV | V |
| Voltage type | median 330–470 → line-line; 180–270 → phase-neutral; ~11000 → HV side (warn) | phase-neutral V (L-L / √3, flagged `DERIVED_VLN`) |
| Temperature | header `°F`/`F`, or values 80–250 typical → °F; > 250 → K | °C |
| Power | header `W` vs `kW` / `MW`; magnitude vs rating | kW, kVAr, kVA |
| PF | 0–100 → divide by 100 | 0–1 |
| Oil level | 0–1 fraction → ×100; mm/cm → needs config (flag) | % |
| Loading | 0–1.5 fraction → ×100 | % |

Every conversion is logged in the Data Health Report.

### 2.6 DERIVE (ladder; each derived value flagged `DERIVED_<COL>`)

Current input to the twin must be **amps on the LV side** (library requirement — per-unit is silently misread as amps).

| Available | Derive |
|---|---|
| IR, IY, IB | `I_mean` = mean; unbalance; neutral proxy (if no IN) |
| `I_total` only | IR = IY = IB = I_total; **unbalance analytics disabled** |
| `S_kVA` only | I = S·1000 / (√3 · V_LL) using measured V or nameplate V |
| `P_kW` + `PF` | S = P / PF, then as above |
| `loading_pct` only | I = loading/100 · I_rated |
| V L-L only | V L-N = V L-L / √3 |
| V, I | S, and P if PF present |

### 2.7 ENRICH

- **Ambient:** use `ATI_C` if present and valid; else Open-Meteo cached hourly for the site (interpolated to the data interval); else a configurable constant/diurnal profile flagged `ASSUMED_AMBIENT`. If the data's dates aren't covered by the cache, use same-calendar-day climatology from the cache, flagged.
- **Humidity:** `RH_pct` from file, else Open-Meteo, else disabled (breathing index off).
- **Nameplate:** from a nameplate sheet if found; else `config/asset.yaml`; else UI form. If rating is unknown, estimate `I_rated` as the 99th percentile of current / 0.8, flagged **[Assumed — estimated from data]** with a red banner.

### 2.8 VALIDATE → `dq_flags`

| Code | Rule (configurable) |
|---|---|
| `DUP_IDENT`, `DUP_CONFLICT` | 2.3 |
| `GAP` | spacing > 3× interval |
| `RANGE_<COL>` | outside physical range (e.g., OTI < −10 or > 150 °C; V L-N < 100 or > 300) |
| `JUMP_OTI`, `JUMP_WTI` | rate > 5 °C per 15 min (scaled to interval) |
| `STUCK_<COL>` | unchanged ≥ 8 samples while load changes > 10% |
| `ATI_MISMATCH` | ATI vs Open-Meteo differs > 8 °C for > 6 h |
| `NEG_<COL>` | negative current/power where impossible |
| `IMPUTED_*`, `DERIVED_*`, `ASSUMED_*` | provenance of filled values |
| `MERGE_CONFLICT` | 2.2 |

Flagged values are **kept**, not deleted; P3's sensor-fault module consumes them.

### 2.9 CAPABILITY MATRIX (drives the whole app)

Computed once per dataset, stored in `df.attrs["capabilities"]`, shown on the Data Health page.

| Module / feature | Needs | If missing |
|---|---|---|
| Thermal twin (estimated temps) | current (any route) + ambient (any route) | Cannot run → app shows data-only view |
| Residual detector, fidelity | + `OTI_C` | **Meter-only mode** (estimated temps shown) |
| Hot-spot check vs WTI | + `WTI_C` | Use twin hot-spot only |
| Unbalance (current) | IR, IY, IB | Disabled, banner |
| Voltage quality | VR/VY/VB or L-L | Disabled |
| Neutral current | IN | Proxy from unbalance (labeled proxy) |
| Oil leak / theft | `OLI_pct` | Disabled |
| Through-fault tracker | event table **or** sub-second/`*_max` currents | Disabled with note "needs event log" |
| Breathing index | `OTI_C` or twin oil temp + `RH_pct` | Disabled |
| Aging / RUL | twin hot-spot | Always on if twin runs |
| Lead-time evaluation | ground-truth columns | Disabled (normal for real data) |

**Mode:** `full` if OTI present, `meter_only` if not, `data_only` if twin can't run.

---

## 3. Output contracts

### 3.1 Canonical trend table

| Column | Unit | Required |
|---|---|---|
| `timestamp` | tz-aware, Asia/Kolkata | ✅ |
| `IR`, `IY`, `IB`, `I_mean` | A (LV) | ✅ (`I_mean` at minimum) |
| `IN` | A | optional |
| `VR`, `VY`, `VB` | V (L-N) | optional |
| `S_kVA`, `P_kW`, `Q_kVAr`, `PF`, `freq_Hz` | — | optional |
| `loading_pct` | % of rated | ✅ (derived) |
| `OTI_C`, `WTI_C`, `ATI_C` | °C | optional |
| `amb_C` | °C | ✅ (enriched) |
| `RH_pct` | % | optional |
| `OLI_pct` | % | optional |
| `alarm_*` | 0/1 | optional (display only) |
| `gt_*` | — | optional (eval only) |
| `extra_*` | — | optional (raw view) |
| `dq_flags` | `;`-separated codes | ✅ |
| `source` | `generated_sim` / `kaggle_real` / `organizer` / `replay` / `live` | ✅ |
| `simulated` | bool | ✅ |

### 3.2 Canonical event table

| Column | Unit |
|---|---|
| `timestamp` | tz-aware |
| `event_type` | `through_fault`, `trip`, `tamper`, `alarm`, `other` |
| `phase` | R/Y/B/3ph/unknown |
| `peak_pu` | × I_rated (derived from peak A if given) |
| `duration_ms` | ms |
| `i2t_pu2s` | peak_pu² × s (derived) |
| `source`, `simulated` | as above |

### 3.3 Data Health Report (page + JSON)

Rows read, rows after cleaning, time span, interval, mapping table with confidences, unit conversions applied, derived channels, flag counts by code, capability matrix, mode, nameplate source (confirmed/assumed/estimated). Exported in the PDF report's appendix.

---

## 4. Interfaces

```python
# ingest/adapter.py
def inspect(paths: list[str]) -> InspectResult:
    """Read + shape + time + auto-map proposal. No changes committed. Used by the Import UI."""

def load(paths: list[str], schema: str | dict | None = None,
         asset: str = "config/asset.yaml") -> Dataset:
    """Full pipeline. schema=None → auto-map (confidence ≥ 0.6 only)."""

def map_row(raw: dict, schema: dict, asset: dict) -> dict:
    """Same mapping/units/derive for a single streaming row (replay, MQTT, live sensor)."""

@dataclass
class Dataset:
    trend: pd.DataFrame          # 3.1
    events: pd.DataFrame         # 3.2 (may be empty)
    capabilities: dict[str, bool]
    mode: str                    # "full" | "meter_only" | "data_only"
    health_report: dict          # 3.3
    asset: dict                  # resolved nameplate + tags
```

CLI for the drill:
```bash
python -m ingest.adapter inspect path/to/file.xlsx
python -m ingest.adapter load path/to/file.xlsx --save-schema config/schema/finale.yaml
```

---

## 5. Robustness test matrix (P1 builds fixtures, `pytest` runs them)

All fixtures are generated from the Normal scenario so expected outputs are known.

| # | Fixture | Tests |
|---|---|---|
| F1 | Canonical CSV (our own) | Baseline round-trip |
| F2 | Kaggle real files (5 CSVs, `DeviceTimeStamp`, VL1/IL1, OTI…) | Multi-file merge, dupes, real flags |
| F3 | L1/L2/L3 naming, **°F temps**, epoch-ms timestamps | Synonyms, temp + epoch conversion |
| F4 | **Excel, 3 sheets** (trend, events, nameplate), DD/MM/YYYY | Sheet roles, Indian dates, events, nameplate |
| F5 | **Long historian format** (`ts, tag, value`) | Pivot |
| F6 | **Line-line voltages only, kA currents** | Unit + L-L→L-N |
| F7 | **Loading % only + ambient**, no temps | Derive amps; meter-only mode |
| F8 | **kVA only**, no ambient | Derive amps; Open-Meteo enrichment |
| F9 | Total current only, semicolon CSV, latin-1, 3 metadata rows on top | Sniffing; unbalance disabled |
| F10 | A/B/C naming with `ib` ambiguity | Phase scheme resolution |
| F11 | Contains `fault_label` column | Quarantined to `gt_*`, not used by detectors |
| F12 | Two transformers in one file | Asset selection |
| F13 | 1-second data with spikes | Resample + `*_max` → events |
| F14 | Hourly data with 2-day gap | Coarse warning, GAP, twin restart |

**Pass criteria:** every fixture loads without exception; capability matrix matches expected; twin `I_mean` within 1% of the known truth; mode correct.

**Finale drill (rehearse twice):** someone not on P1 makes a fresh, weird CSV; P1 gets it running in the dashboard in ≤ 15 minutes using only the Import page / YAML.

---

## 6. Extensibility (what we say to judges)

- **Real sensors / DTMU / SCADA:** `map_row()` is the same mapping used for files; a live MQTT or GPRS feed plugs into it with no change downstream.
- **Utility systems:** a historian export (long format) or a DT smart-meter export (meter-only mode) both load through the same adapter.
- **New sites:** new `asset.yaml` + saved schema YAML; no code change.
- **Future naming standard:** canonical names can be aliased to IEC 61850 logical nodes (MMXU, STMP, SIML, YPTR) — future-extension slide only.
