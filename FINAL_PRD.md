# FINAL PRD — Digital Twin of a Distribution Transformer

**PowerNext-AI 2026 (CPRI × MIT Bengaluru) · Track 02** · Team of 4 · 24-hour build · Goal: win

Merges: BUILD_PLAN.md, earlier PRD, final outline, dataset plan, CPRI takeaways. **This document supersedes all of them.** Detailed ingestion design: `DATA_INGESTION_SPEC.md`.

**Tag legend** (use the same tags in submitted docs):
- **[Confirmed]** read from a provided file/photo, a primary source, or tested by us
- **[Reported]** from secondary sources (news coverage), consistent across outlets
- **[Assumed]** our choice; goes in the Assumptions register (§19)
- **[To verify]** check against the primary source before it goes on a slide or becomes a hard constant
- **[Open]** unanswered, with a fallback

---

## 1. What we're building

A software digital twin of one **1000 kVA, 415 V oil-filled distribution transformer** ("Transformer-1", MAHE Bengaluru campus). It ingests **any** operating dataset through a universal adapter, runs an **IEC 60076-7 thermal and ageing model** alongside the measured data, and watches the gap between them. From that it computes a Health Index, alerts with measured lead time, remaining life and maintenance advice phrased as real test names, on a Streamlit dashboard with scenario selection, data import and a downloadable report.

It's organized around **CPRI's three failure causes — overloading, insulation, short circuit** — plus oil leak/theft, unbalance, moisture exposure and sensor/data faults.

> **Pitch line:** Physics says what should happen, data says what is happening, and the AI watches the gap.

### Success criteria (what judges must see)
1. **The organizers' dataset loads and runs** through the Import page.
2. A healthy baseline month with a daily load cycle and plausible temperatures; zero false alarms.
3. Five fault scenarios, each triggering a visibly different, correct response.
4. Alerts with measured **lead time** vs a threshold baseline.
5. A Health Index explainable sub-score by sub-score.
6. Remaining life that drops under overload and stays long under normal load.
7. Recommendations naming specific tests.
8. **Meter-only mode** (temperatures estimated when sensors are absent) — automatic when data lacks temperatures.
9. Real field data (Kaggle) with sensor glitches correctly classified as **data faults, not asset faults**.
10. Self-test panel in CPRI's Excel format.
11. Everything simulated is labeled **SIMULATED**.

---

## 2. Guideline compliance

| Requirement | Source | How we meet it |
|---|---|---|
| "Work with simulated datasets provided during the hackathon" | Problem PDF §2 [Confirmed] | Universal adapter (`DATA_INGESTION_SPEC.md`), auto-map + confirm UI, 14-fixture test matrix, 15-min drill |
| "Extended later to connect with real sensors and utility monitoring systems" | Problem PDF §2 [Confirmed] | `map_row()` streaming path shared with files; historian (long) format; meter-only mode for DT smart meters |
| Data input layer: simulated sensor data, historical datasets, CSV files, IoT data simulator | PDF §4 [Confirmed] | All supported; replay simulator |
| Monitor voltage, current, loading, oil temp, ambient temp | PDF §3 [Confirmed] | Canonical table |
| Health Index, anomaly detection, predictive maintenance, dashboard, reports | PDF §3–4 [Confirmed] | §8–§10 |
| Deliverables: prototype, dashboard, docs (architecture, methodology, assumptions, user guide), source + run instructions, presentation, demo/recorded walkthrough | PDF §6 [Confirmed] | §18 |
| Fair play: no manipulating datasets/benchmarks/demos/results to misrepresent | Official site, rule 01, powernext-ai.in/#rules [Confirmed] | `simulated` column, SIMULATED badges, assumptions register, claims ledger |

**Precise reading:** the PDF requires the solution to work with *their* simulated datasets. Since we don't know the format, we interpret that as "must accept any reasonable DT dataset." That's our design choice, and a strong one.

---

## 3. Pinned facts

### 3.1 The asset (from site photos; no nameplate yet)

| Item | Value | Tag |
|---|---|---|
| Rating | 1000 kVA, "Transformer-1" on the LT kiosk | [Confirmed label] |
| LV system | 415 V (DANGER 415 VOLTS plates) | [Confirmed] |
| Full-load LV current | 1000 / (√3 × 0.415) = **1391 A** | [Calculated]; consistent with 1600 A busduct |
| HV | 11 kV | [Assumed] |
| Vector group | Dyn11 | [Assumed] |
| Cooling | ONAN (radiators, conservator seen) | [Assumed] |
| Losses | Load 10,000 W, no-load 1,100 W | **[Assumed placeholder; replace from nameplate/datasheet]** |
| Insulation | Normal (non-thermally-upgraded) Kraft paper | [Assumed] |
| In service | 3 years | [Assumed until manufacture year known] |
| Breather | Breathing type with silica gel | [Assumed] |

A second 1600 kVA unit exists on campus; not modeled.

### 3.2 The organizers' Excel
A **device acceptance test, not data.** Useful content: fault families (overload, unbalance, short circuit, over-temperature, oil level), accuracy ≤ 1%, trip tests (50 A, 60 °C on the lab rig), "Communication: GPRS and Master Number," "Implementation of AI for further decision making," **R/Y/B phase naming**. [Confirmed]

**Rule:** 50 A and 60 °C are **bench values used only in the self-test panel.** IEC 60076-7's default rated top-oil rise for distribution transformers is 60 K *above ambient*, so a 60 °C absolute operating alarm would fire daily in Bengaluru (our smoke test: 67.5 °C top-oil in normal operation). Operating alarms use §9.

### 3.3 Library facts (tested)
- `transformer-thermal-model` v0.6.0 requires **Python ≥ 3.11** → use 3.12. [Confirmed]
- **Load input must be in amps** (LV side). Per-unit is silently treated as amps → near-ambient temps (40.5 °C vs 67.5 °C on the same profile). [Confirmed]
- Distribution-transformer defaults (ONAN): oil time constant 180 min, top-oil rise 60 K, k11 1.0, k21 1, k22 2, x 0.8, y 1.6, ambient surcharge 10 K, winding time constant 4 min, winding-oil gradient 23 K, hot-spot factor 1.2. [Confirmed from package]
- Ageing for normal paper: relative rate 2^((θh − 98)/6); 1.26 at 100 °C. [Confirmed from package; To verify vs standard text]
- License: **MPL-2.0**. [Confirmed]

---

## 4. Data sources and roles

| Source | Role | Tag |
|---|---|---|
| **Generated campus data** (plant model, §5) | Primary demo dataset for Transformer-1; ground-truth scenarios; lead-time evaluation | Build |
| **Organizers' dataset** | Loaded live via the adapter on the day | [Open] format unknown |
| **Kaggle "Distributed Transformer Monitoring"** — `kaggle.com/datasets/sreshta140/ai-transformer-monitoring` | "Real field data" page: adapter demo, data-quality flags, sensor-vs-asset faults, a twin **fitted to that unit** | [Confirmed]: Jun 2019–Apr 2020, 15-min; files CurrentVoltage/Overview/Power/PowerFactor/TotalPower; OTI, WTI, ATI, OLI, OTI_A, OTI_T, MOG_A (= magnetic oil gauge indicator), VL1–3, IL1–3, INUT |
| **Open-Meteo** (Bengaluru hourly temperature + RH, cached offline) | Real ambient/humidity for generator and enrichment | [Open] permission to download; fallback synthetic ambient |
| **ETT** (github.com/zhouhaoyi/ETDataset) | Optional realism check of oil-temperature dynamics | LICENSE reads CC BY-ND 4.0: validation only, cite Zhou et al. AAAI 2021, no modified copies |

**Kaggle rules:**
- It's a **different, unrated transformer**. Never calibrate Transformer-1 on it. Fit a separate twin to it (rating and rise fitted from data, tagged [Assumed — fitted]).
- Known issues (audit repo `MohamedMehery/transformer-telemetry-integrity-audit`): duplicate timestamps in every file (Overview: 931 groups, 363 conflicting); abrupt OTI jumps; uncertain single-asset continuity. Clean and flag, don't hide.
- `MOG_A` = "oil gauge alarm," never "leak label." Check MOG_A vs OLI correlation and report it.
- **Never** use `OTI_A`/`OTI_T`/`MOG_A` as ML targets or features (label leakage — how public notebooks claim "99% AUC").

---

## 5. Generated campus data ("plant" vs "twin")

### 5.1 Method
1. Per-unit load profile: weekday daytime peak (~08:00–18:00), lower nights/weekends, mild ambient coupling, noise. Typical peak 0.55–0.75 pu [Assumed]. **Convert to amps (× 1391) before the library.**
2. Split to IR/IY/IB with natural ±2% imbalance.
3. **Plant** = library with *perturbed* parameters (top-oil rise ± a few %, hot-spot factor slightly different) + sensor noise (≈ 0.3–0.5 °C temps, ≈ 0.3% V/I). This is the "measured" data.
4. **Twin** = nominal parameters. Mismatch is deliberate so fidelity isn't circular; stated openly.
5. Faults injected into the **plant only**, per `scenarios.yaml`.
6. Fixed seed; one run per scenario; reproducible.
7. Window: 30 days, 15-min (2880 rows), April 2026 [Open; hottest month].

### 5.2 Scenarios (`config/scenarios.yaml`, magnitudes [Assumed], tune visually)

| ID | Injected into the plant | Expected detector |
|---|---|---|
| **N** Normal | Nothing | None (false-alarm test) |
| **S1** Overload | Days 24–26: daytime 1.15–1.35 pu, 6–10 h/day | Loading + hot-spot alarms, ageing rate ↑, RUL ↓ (twin explains it; residual stays small) |
| **S2** Cooling degradation | From day 20: top-oil rise multiplier ramps to ~1.25 | **Residual drift** before any absolute threshold |
| **S3** Unbalance | From day 25: one phase +12–18%, another −8% | Unbalance %, neutral proxy |
| **S4** Oil loss | (a) leak: 100 → ~78% over 5 days; (b) theft: night step −10 to −15 points, no thermal cause | Leak vs theft classifier |
| **S5** Through-faults | Day 27: ~6× for 300 ms, ~10× for 500 ms, one moderate — **event table only** | Through-fault stress → %X recommendation |

Short circuits live **only in the event table** (15-min averages can't show them).

### 5.3 Files
`data/generated/trend_<ID>.csv` and `events_<ID>.csv`, written **in canonical format** (so they go through the same adapter as everything else — F1 fixture).

---

## 6. Ingestion — any data in

Full design: **`DATA_INGESTION_SPEC.md`**. Summary:

- **Reads** CSV/TSV/XLSX (all sheets)/JSON/Parquet/ZIP, multiple files, long historian format, multi-asset files.
- **Time:** ISO, DD/MM (Indian default), epoch, Excel serial, split date/time; dedupe; interval detection; gaps.
- **Auto-mapping** via synonym dictionary + unit hints + value ranges, with confidence; **Import page** to confirm/edit; mappings saved as YAML and reused.
- **Units:** kA/kV/°F/K/L-L/fractions → canonical.
- **Derive ladder:** per-phase from total, amps from kVA or loading %, L-N from L-L — always flagged.
- **Enrich:** ambient/RH from Open-Meteo cache; nameplate from file → `asset.yaml` → UI → data estimate (red banner).
- **Validate:** `dq_flags` (dupes, gaps, ranges, jumps, stuck, ATI mismatch).
- **Capability matrix** decides which modules run; **mode** = `full` / `meter_only` / `data_only`. Missing data turns features off; it never crashes the app.
- Ground-truth columns quarantined to `gt_*` (evaluation only); device alarm flags display-only.
- Same `map_row()` for streaming → real sensors later.

---

## 7. Twin engine

### 7.1 Library usage (verified)
```python
from transformer_thermal_model.schemas import InputProfile, UserTransformerSpecifications
from transformer_thermal_model.transformer import DistributionTransformer, PaperInsulationType
from transformer_thermal_model.model import Model
from transformer_thermal_model.aging import aging_rate_profile, days_aged

specs = UserTransformerSpecifications(load_loss=W, no_load_loss=W, nom_load_sec_side=1391)  # AMPS
tr = DistributionTransformer(user_specs=specs)                                             # ONAN
prof = InputProfile.create(datetime_index=idx, load_profile=amps, ambient_temperature_profile=amb)
out = Model(temperature_profile=prof, transformer=tr).run()
df = out.convert_to_dataframe()      # top_oil_temperature, hot_spot_temperature
rate = aging_rate_profile(out.hot_spot_temp_profile, PaperInsulationType.NORMAL)
```
Input load = `I_mean` (A). Thin wrapper `twin/thermal.py` so the library can be swapped. Long gaps → restart from steady state (flagged).

### 7.2 Outputs per timestep
`twin_oil_C`, `twin_hs_C`, `aging_rate`, `days_aged_cum`, `residual_oil_C` (= OTI − twin, NaN in meter-only), `fidelity_rmse_C` (rolling 24 h), `load_pu`.

Fidelity above threshold → dashboard: **"model drift — check cooling / recalibrate."** (CIGRE JWG A2/D2.65 "reality gap" framing.)

### 7.3 Meter-only mode
Automatic when OTI is absent; also a manual toggle for demo. Shows estimated oil and hot-spot from load + ambient; residual detector disabled. Pitch: runs on DT smart-meter data alone.

### 7.4 Fitted twin (Kaggle / unknown-rating data)
When nameplate is estimated, fit top-oil rise and hot-spot factor (and `I_rated` if needed) on the first 2/3 of the data, test on the last 1/3; report RMSE. Tagged [Assumed — fitted].

---

## 8. Analytics modules

### 8.1 Three headline modules (CPRI)
CPRI's journal abstract names **short circuits, insulation breakdown and prolonged overloading** as prime DT outage causes (Prabakaran et al., *Power Research* 19(1), 2023, doi:10.33686/pwj.v19i1.1109) [Confirmed — abstract].

| Module | What the twin does | Honest limit |
|---|---|---|
| Overloading | Loading %, hot-spot vs limits, ageing rate | — |
| Insulation | Loss of life, RUL, breathing index | Thermal ageing only; no moisture/PD/DGA; no breakdown-date claims |
| Short circuit | Through-fault event counter & stress | Needs an event log; 15-min trend can't see faults |

### 8.2 Through-fault stress tracker
- Per event: `peak_pu`, `duration_ms`, `i2t_pu2s`. Cumulative stress = Σ I²t.
- Classes: moderate ≥ 3 pu, severe ≥ 8 pu [Assumed].
- Rule: 1 severe or N moderate (default 3) since reset → **"Measure short-circuit impedance (%X) and compare with the IS 1180 acceptance limit."**
- IS 1180 limits: ≤ 2% change (circular coils), ≤ 7.5% (non-circular concentric) — from **CPRI Bhopal's IS 1180:2014 presentation** [Confirmed from CPRI deck; To verify vs standard text]. Configurable.

### 8.3 Electrical quality
- Current unbalance % = max |Iφ − Imean| / Imean × 100. Voltage unbalance likewise.
- Neutral: measured `IN` if present; else **unbalance-based proxy, labeled proxy.** No earthing claims.
- Over/undervoltage vs configurable pu limits [To verify vs Indian supply regulations].

### 8.4 Oil: leak vs theft
- Slow slope over hours/days → **leak**.
- Step in a few samples, no thermal cause, especially night → **possible theft/tampering** (CEA lists oil theft/tampering among external DT failure causes [Reported]).
- Low-level alarm configurable.

### 8.5 Breathing-stress index [experimental, uncalibrated]
Accumulated daily top-oil swing × RH. Our heuristic; labeled "experimental, not validated." Breathing units only. Not tied to any "90% of failures" claim.

### 8.6 Sensor fault vs asset fault
Consumes `dq_flags` + physics checks: impossible rate of change vs thermal time constant, stuck sensors, ATI vs weather mismatch, inconsistent V/I. Each alert has `origin = asset | sensor`. Sensor alerts recommend **"check the device, not the transformer."** Demonstrated on real Kaggle glitches.

### 8.7 Anomaly detection (three layers)
1. **Rules** with hysteresis (§9).
2. **Residual detector:** persistent offset / drift of measured − twin oil temp (CUSUM or rolling mean vs threshold set from the Normal scenario's residual distribution).
3. **IsolationForest** on [residual, loading, unbalance, oil-level slope], trained on Normal only. Second opinion; not oversold.

### 8.8 Health Index (0–100)

| Sub-score | Driven by | Weight [Assumed] |
|---|---|---|
| Thermal | hot-spot & oil temp vs limits | 30 |
| Ageing | recent ageing rate, consumed life | 25 |
| Loading | loading history | 15 |
| Electrical quality | unbalance, voltage deviation | 15 |
| Integrity | oil level, leak/theft flags | 10 |
| Fault stress | through-fault counter | 5 |

Piecewise-linear sub-scores from `thresholds.yaml`. Weights renormalize over **available** sub-scores (capability matrix). **Weakest-link cap:** any critical asset alarm caps HI at 40. Bands: Green ≥ 80, Yellow 60–79, Red < 60 [Assumed]. Stated as a transparent engineering score, not a trained one. CEA has proposed health indexing of DTs [Reported].

### 8.9 Remaining useful life
- Consumed = assumed service years + accumulated ageing (equivalent days).
- Reference life: 180,000 h (~20.55 y) per IEC 60076-7 [To verify].
- RUL = (reference − consumed) / recent 7-day ageing rate → shown as a **range** + risk class (Low/Med/High) [Assumed cut-offs].
- Under normal Bengaluru load, ageing rate ≪ 1 → RUL long. Correct; say so. The point is how overload converts into lost life.

### 8.10 Recommendation engine (`analytics/recommend.py`)

| Condition | Action / test | Urgency |
|---|---|---|
| Residual up + oil level down | Oil leakage check; insulation resistance test | 24 h |
| Persistent residual offset (cooling) | Inspect radiators/cooling; check oil level | 7 d |
| Through-fault stress crossed | Short-circuit impedance (%X) measurement vs IS 1180 limit | 7 d |
| Sustained overload / high ageing | Load review/transfer; check cooling; inspection | 24 h–7 d |
| Unbalance high | Rebalance single-phase loads; check connections & neutral | 7 d |
| Sudden night oil drop | Site inspection for theft/tampering | Immediate |
| High breathing index | Inspect silica-gel breather; oil moisture / BDV test | Next scheduled |
| HI degradation | Tan-delta / insulation assessment; winding resistance if winding suspected | 7 d |
| Abnormal losses suspected | No-load / load loss measurement | Next scheduled |
| Sensor/data fault | Check sensor wiring/calibration; not the transformer | 24 h |

Each recommendation: action, test, urgency, reason (triggering signal), linked alert ID, standard reference. Tan-delta being a CEA recommendation for DTs: [Reported; To verify].

---

## 9. Thresholds (`config/thresholds.yaml`)

**Operating (Transformer-1, all configurable):**

| Parameter | Default | Tag |
|---|---|---|
| Loading warning / alarm | 0.9 / 1.0 pu | [Assumed] |
| Overcurrent alarm | 1.2 pu | [Assumed] |
| Top-oil warning / critical | 85 / 95 °C | [Assumed; To verify vs IEC 60076-7 DT limits] |
| Hot-spot warning / critical | 98 / 120 °C | [Assumed; 98 °C = ageing rate 1; 120 °C To verify] |
| Current unbalance warning / alarm | 10 / 20 % | [Assumed] |
| Voltage unbalance alarm | 2 % | [Assumed] |
| Voltage high / low | 1.06 / 0.94 pu | [To verify vs Indian regulations] |
| Oil level low | 85 % | [Assumed] |
| Theft step | ≥ 8 points within 1 h, no thermal cause | [Assumed] |
| Residual alert | auto: mean + 4σ of Normal residual, persistent ≥ 2 h | [Assumed] |
| Through-fault moderate / severe / count | 3 pu / 8 pu / 3 | [Assumed] |
| Hysteresis | clear at 95% of trip level | [Assumed] |

**Bench (self-test panel only):** overcurrent trip 50 A; temperature trip 60 °C; accuracy pass ≤ 1%. [Confirmed from Excel]

---

## 10. Dashboard (Streamlit multipage)

Global: scenario/dataset selector, replay speed, play/pause, meter-only toggle, **SIMULATED banner** whenever `simulated` rows are shown.

| Page | Contents |
|---|---|
| **Import** | Upload any file(s), auto-mapping table with confidences, preview, unit detections, save mapping, load |
| **Data Health** | Data Health Report: rows, span, interval, flags, conversions, derived channels, capability matrix, mode, nameplate source |
| **Overview** | HI gauge + sub-scores, risk class, RUL range, active alerts, mini trends |
| **Loading & Temperatures** | Loading %, R/Y/B currents & voltages, measured vs twin oil temp, hot-spot, ambient, residual, fidelity |
| **Failure Modules** | Overloading · Insulation · Short circuit; plus oil leak/theft, unbalance, moisture, through-fault log |
| **Alerts & Maintenance** | Alert feed (asset vs sensor origin, detector, lead time), recommendation table |
| **Real Field Data** | Kaggle unit: fitted twin, data-quality flags, sensor-fault alerts (different transformer, labeled) |
| **Self-Test** | Excel format: reference vs software, % diff, pass ≤ 1%, 50 A / 60 °C trips, oil channel, "status to master number" (Telegram, with in-app fallback) |
| **Reports** | PDF summary (incl. Data Health appendix), CSV export, lead-time table |
| **About** | Twin definition (CIGRE JWG A2/D2.65), architecture, assumptions register, citations, fidelity explanation |

Replay via `st.fragment(run_every=…)` (confirm version) or equivalent. Plotly. Green/yellow/red only for health state. Fully offline-capable.

---

## 11. Evaluation

| Result | Method | Owner |
|---|---|---|
| **Lead time** | Per scenario: hours between first twin alert and (a) first baseline-threshold crossing, (b) ground-truth onset. Baseline = plain thresholds only | P3 |
| **False alarms** | On Normal (target 0); also per month on cleaned Kaggle | P3 |
| **Twin fidelity** | Rolling RMSE on Normal (mismatch caveat stated); fitted-twin test RMSE on Kaggle | P2 |
| **Ingestion robustness** | 14-fixture matrix passes | P1 |
| ETT realism (stretch) | Compare oil dynamics qualitatively | P2 |

---

## 12. Contracts (freeze at hour 2)

### 12.1 Repo layout & ownership
```
dt-twin/
├── README.md  requirements.txt  THIRD_PARTY.md                    P4
├── config/
│   ├── asset.yaml          (tagged nameplate)                      P2
│   ├── thresholds.yaml                                             P3
│   ├── scenarios.yaml                                              P2
│   ├── synonyms.yaml                                               P1
│   └── schema/*.yaml       (saved mappings: kaggle, ett, finale)   P1
├── contracts/
│   ├── canonical.py        (columns, units, validate())            P1
│   └── models.py           (dataclasses §12.3)                     P1+P3
├── ingest/   adapter.py read.py shape.py time.py map.py units.py derive.py enrich.py validate.py capabilities.py   P1
├── sim/      generator.py (plant, scenarios, events)               P2
│             replay.py                                              P1
├── twin/     thermal.py ageing.py rul.py fit.py engine.py          P2
├── analytics/ rules.py residual.py anomaly.py sensor_faults.py electrical.py oil.py through_fault.py breathing.py health.py recommend.py pipeline.py   P3
├── eval/     lead_time.py false_alarms.py fidelity.py              P3 (fidelity P2)
├── app/      streamlit_app.py + pages/*                            P4
├── alerts/   telegram.py                                           P4
├── reports/  pdf.py                                                P4
├── data/     generated/ raw/ cache/weather/ fixtures/ PROVENANCE.md P1 (generated: P2)
├── tests/                                                          each owner
└── docs/     architecture.md methodology.md assumptions.md user_guide.md qa_prep.md   P4 (+all)
```

### 12.2 Interfaces
```python
# ingest/adapter.py (P1)
def inspect(paths) -> InspectResult
def load(paths, schema=None, asset="config/asset.yaml") -> Dataset
def map_row(raw: dict, schema: dict, asset: dict) -> dict

# sim/generator.py (P2)
def generate(scenario_id: str, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]  # canonical trend, events

# sim/replay.py (P1)
class Replay:  # iterates canonical rows at chosen speed, fixed seed
    def __init__(self, ds: Dataset, speed: float = 60.0): ...
    def __iter__(self) -> Iterator[dict]: ...

# twin/engine.py (P2)
class TwinEngine:
    def __init__(self, asset: dict, fitted: dict | None = None): ...
    def run(self, ds: Dataset) -> pd.DataFrame          # trend + twin columns (§7.2)
    def step(self, row: dict) -> TwinState               # streaming
def fit(ds: Dataset, asset: dict) -> dict               # §7.4

# analytics/pipeline.py (P3)
def analyze(df_twin: pd.DataFrame, events: pd.DataFrame, caps: dict, thresholds: dict) -> AnalysisResult
class StreamAnalyzer:
    def update(self, state: TwinState, new_events: list[dict]) -> AnalysisResult
```

### 12.3 Shared dataclasses (`contracts/models.py`)
```python
@dataclass
class Dataset:
    trend: pd.DataFrame; events: pd.DataFrame; capabilities: dict[str, bool]
    mode: str; health_report: dict; asset: dict

@dataclass
class TwinState:
    timestamp: pd.Timestamp; row: dict; twin: dict; mode: str

@dataclass
class Alert:
    id: str; timestamp: pd.Timestamp
    module: str        # overloading | insulation | short_circuit | electrical | oil | moisture | data
    type: str          # e.g. residual_drift, through_fault, oil_theft, oil_leak, jump_oti, unbalance
    severity: str      # info | warning | critical
    origin: str        # asset | sensor
    detector: str      # rule | residual | ml | physics
    value: float | None; threshold: float | None
    explanation: str; recommendation_id: str | None
    simulated: bool; lead_time_h: float | None

@dataclass
class Recommendation:
    id: str; action: str; test: str | None; urgency: str   # immediate | 24h | 7d | next_scheduled
    rationale: str; alert_id: str; standard_ref: str | None

@dataclass
class Health:
    score: float; band: str; components: dict[str, float]; weights: dict[str, float]; capped: bool

@dataclass
class RUL:
    years_low: float; years_high: float; risk: str; consumed_days: float; recent_rate: float

@dataclass
class AnalysisResult:
    alerts: list[Alert]; recommendations: list[Recommendation]
    health: Health; rul: RUL | None; fidelity_rmse_C: float | None
```

**Rule:** every owner ships a **stub with the real interface** at hour 2 (returns correctly-shaped empty/NaN outputs). Nobody waits on finished work. Contract changes need all four to agree.

---

## 13. Team split

| Role | Person | Owns |
|---|---|---|
| **P1 Data** | ______ | Universal adapter, synonyms, fixtures & robustness tests, Open-Meteo cache, Kaggle download/cleaning/provenance, replay, finale drill |
| **P2 Physics** | ______ | `asset.yaml`, generator (plant vs twin, 6 scenarios, events), twin wrapper, ageing, RUL, fitted twin, fidelity, amps regression test |
| **P3 Intelligence** | ______ | Thresholds, rules + hysteresis, residual detector, IsolationForest, sensor-vs-asset, electrical, oil leak/theft, through-fault, breathing, HI, recommendations, lead time, false alarms |
| **P4 Product** | ______ | Repo/README, dashboard (all pages incl. Import & Data Health UI on P1's API), self-test, Telegram, PDF, docs, deck, demo script, backup video, Q&A, integration checkpoints, `main` merges |

### Work packages & acceptance

**P1 — Data**
| Task | Done when |
|---|---|
| `contracts/canonical.py`, `models.py` (with P3) + stubs | Merged hour 2 |
| Mock canonical sample (7 days) | Delivered hour 2 |
| Adapter steps 1–9 | All 14 fixtures pass (`DATA_INGESTION_SPEC.md` §5) |
| Synonyms + Import API (`inspect`) | P4's Import page can render proposals |
| Open-Meteo cache | Works with network off |
| Kaggle download, cleaning, PROVENANCE, MOG_A vs OLI note | Flag counts logged |
| Replay | Same seed → same stream |
| Finale drill | Unseen CSV running in ≤ 15 min, twice |

**P2 — Physics**
| Task | Done when |
|---|---|
| venv 3.12, smoke test with 1391 A | Library runs in project venv |
| `asset.yaml` with tags | Values traced to photos/assumptions |
| Generator: Normal first, plotted | Peak oil temp & ageing look physical |
| Scenarios S1–S5 + events | Each plotted; ground truth in `gt_*` |
| Twin wrapper, residual, fidelity | Normal: residual ≈ 0 ± noise |
| Ageing, RUL | Rate ≈ 1.26 at 100 °C test passes |
| Fitted twin on Kaggle | Train/test RMSE reported |
| `run()` == `step()` | Batch vs streaming test passes |

**P3 — Intelligence**
| Task | Done when |
|---|---|
| `thresholds.yaml` (operating + bench) | Reviewed by P2 |
| Rules + hysteresis | Unit tests per alarm |
| Residual detector (threshold from Normal) | Fires on S2 before baseline |
| IsolationForest (Normal only, seeded) | No alarm flags/gt used |
| Sensor-vs-asset | Kaggle OTI jumps → `origin=sensor` |
| Electrical, oil leak/theft, through-fault, breathing | Each scenario triggers its detector; Normal triggers none |
| HI with renormalization + cap | Bounds & cap tests pass |
| Recommendations | Every alert type maps to ≥ 1 rec |
| Lead time & false alarms | Table + plot in `docs/figures/` |
| `analyze()` == `StreamAnalyzer` | Test passes |

**P4 — Product**
| Task | Done when |
|---|---|
| Repo, README, one-command run | Fresh-laptop install works |
| Walking skeleton (mock → stubs → UI) | Hour 5 |
| All pages (§10) | Each renders for full / meter-only / data-only modes |
| Import + Data Health UI | Fixture F4 loaded through UI end to end |
| Self-test panel | Excel format reproduced |
| Telegram + fallback, PDF report | Work offline (fallback) |
| Docs (§18), THIRD_PARTY, assumptions, ledger | All PDF-required sections exist |
| Deck, demo script, backup video, `qa_prep.md` | Timed rehearsal under limit |

---

## 14. Timeline (24 h, four parallel lanes)

| Hours | P1 Data | P2 Physics | P3 Intelligence | P4 Product | Gate |
|---|---|---|---|---|---|
| 0–2 | Contracts, mock data, synonyms draft, Kaggle download | venv 3.12, smoke test (amps), `asset.yaml` | `thresholds.yaml`, `models.py` with P1 | Repo, README, app shell, email organizers (rubric, data format) | **G1: contracts frozen, stubs merged** |
| 2–5 | Adapter steps 1–5, fixtures F1–F6 | Generator Normal + plots | Rules + hysteresis on mock | Walking skeleton | **G2: mock → stubs → UI end to end** |
| 5–8 | Steps 6–9, F7–F14, Open-Meteo cache | Twin wrapper, residual, fidelity, ageing, RUL; scenarios S1–S5 | Residual detector, electrical, oil, through-fault | Overview, Loading & Temps pages | **G3: Normal scenario real end to end, HI green, 0 alarms** |
| 8–11 | Kaggle cleaning, provenance, replay | Fitted twin on Kaggle, `run()`==`step()` | Sensor-vs-asset, IsolationForest, HI, recommendations, breathing | Failure Modules, Alerts, Import, Data Health pages | **G4: each scenario triggers its detector** |
| 11–16 | Finale drill #1, adapter hardening | Tuning, ETT check (stretch) | Lead time, false alarms, figures | Real Field Data, Self-Test, Reports pages; replay | **G5: full demo path works** |
| 16–18 | Drill #2 | Methodology sections | Methodology sections | PDF, Telegram, meter-only polish | **G6 (hour 18): FEATURE FREEZE** |
| 18–22 | Docs: data, user guide input | Docs: twin, assumptions | Docs: analytics, ledger | Docs assembly, deck, rehearsal ×2 | All deliverables present |
| 22–24 | Clean-checkout test | Bug fixes | Bug fixes | Backup video, final run | Fresh-install passes |

### Integration checkpoint (P4 runs at every gate, fresh clone, network off)
1. `pip install -r requirements.txt` succeeds (Python 3.12).
2. `pytest` passes.
3. Adapter loads F1, F2 (Kaggle), and one random fixture.
4. Dashboard starts and replays end to end offline.
5. Batch == streaming (twin and analytics).
6. SIMULATED badges on all simulated rows/alerts.
7. Mode switches correctly (full / meter-only / data-only fixture).
8. No page crashes on any capability combination.

Failures are the owner's top priority before new work. One branch per task, small PRs, reviewer from another role.

### Cut order if behind
Breathing index → IsolationForest → Telegram → ETT check → PDF (fallback CSV + HTML) → Real Field Data fitted twin (keep data-quality view) → self-test polish.

**Never cut:** adapter + Import page, generator, twin, HI, the scenarios, Overview, docs.

---

## 15. Tests (`pytest`)
- **Amps regression:** library load input in amps (per-unit pitfall).
- Ageing rate ≈ 1.26 at 100 °C.
- Normal → no critical alerts; each scenario → intended detector.
- HI within 0–100; cap at 40 on critical; renormalization with missing sub-scores.
- Generator reproducible for a fixed seed.
- `run()` == `step()`; `analyze()` == `StreamAnalyzer`.
- **14 ingestion fixtures** (`DATA_INGESTION_SPEC.md` §5).
- `gt_*` and `alarm_*` never reach detectors (assert in pipeline).

---

## 16. Demo script (~5–6 min)
1. **Hook:** ~1.3 million DT failures/year in India; CEA pushing health indexing; CESC reported ~0.5% with it.
2. **Organizers' data:** upload → auto-map → Data Health → running. (Or an unseen fixture if theirs isn't available.)
3. **Normal month:** green HI, long RUL, zero alarms; measured vs twin overlay.
4. **Meter-only:** toggle; temperatures estimated from load + ambient.
5. **S2 cooling degradation:** residual alert N hours before the threshold baseline — show lead-time table.
6. **S1 overload:** ageing rate up, RUL drops.
7. **S4 leak vs theft:** two different alerts and recommendations.
8. **S5 through-faults:** stress counter → %X test recommendation.
9. **Real field data:** Kaggle glitches flagged as sensor faults, not asset faults.
10. **Self-test panel** in CPRI's Excel format.
11. **Download report.**
12. **Next steps with CPRI:** validate against CPRI temperature-rise (heat-run) test data; pilot on campus/BESCOM DTs.

Backup video of the full demo always ready.

---

## 17. Judge Q&A (rehearse; answers in `docs/qa_prep.md`)
1. How is this a twin and not a dashboard? → physics model in the loop, residual, what-if, fidelity.
2. How did you validate the thermal model? → plant/twin mismatch on generated data; fitted twin train/test on real Kaggle data; honest about no heat-run data yet.
3. What's real and what's simulated? → `simulated` column, badges, ledger.
4. What if a sensor fails or lies? → sensor-vs-asset module.
5. Why not just thresholds? → lead-time table vs baseline.
6. What does MOG_A mean? → oil gauge alarm; checked vs OLI; not used as a label.
7. Where does RUL come from? → IEC 60076-7 thermal ageing; range; upper bound.
8. Can it handle our data? → adapter, capability matrix, live demo.
9. Cost and scale? → meter-only mode on existing DT meters; software-only.
10. Standards? → IEC 60076-7, IS 1180 test vocabulary, CIGRE twin definition.
11. Why 60 °C isn't your alarm? → rated top-oil rise is 60 K above ambient; 60 °C is a bench setpoint.

---

## 18. Documentation deliverables
1. Solution architecture (layers: data input/adapter → twin engine → analytics → dashboard → reporting; diagram)
2. Methodology (§5–§8 with equations and citations)
3. Assumptions (§19)
4. User guide (incl. "loading your own data")
5. Source code + run instructions (README)
6. Presentation + live demo / recorded walkthrough

**Citations:** IEC 60076-7; Alliander `transformer-thermal-model` (MPL-2.0); Kaggle dataset (sreshta140) + audit repo; Open-Meteo; ETT / Zhou et al. AAAI 2021 (if used); CPRI *Power Research* 19(1) 2023; CPRI Bhopal IS 1180:2014 presentation; CEA Standardisation Cell coverage (Mercom, T&D India); CIGRE JWG A2/D2.65 ToR.

---

## 19. Assumptions register
1. 1000 kVA, 11 kV/415 V, Dyn11, ONAN; only 1000 kVA and 415 V from site labels.
2. Losses are placeholders until nameplate/datasheet.
3. Normal Kraft paper; reference life per IEC 60076-7 [To verify].
4. 3 years in service until manufacture year known.
5. Campus load profile, fault magnitudes, scenario timing are synthetic.
6. HI weights, bands, severity classes, risk cut-offs are engineering choices.
7. Breathing index is an uncalibrated heuristic; breathing-type unit assumed.
8. Twin is thermal; electrical quantities monitored not simulated; neutral current proxied when not measured; no earthing claims.
9. Plant–twin mismatch and noise injected deliberately.
10. Rooftop solar on LV bus ignored.
11. Operating thresholds rescaled for 1000 kVA; Excel's 50 A / 60 °C used only in self-test.
12. Kaggle unit is a different transformer; its twin is fitted, not nameplate-based.
13. Adapter-derived/estimated values (derived channels, estimated rating, imputed ambient) are flagged and listed in the Data Health Report.

---

## 20. Claims ledger (updated)

| Claim | Source | Status |
|---|---|---|
| Library implements IEC 60076-7, distribution ONAN, ageing | Package README/code | Confirmed |
| Python ≥ 3.11; load in amps | Tested | Confirmed |
| Hackathon, CPRI × MIT Bengaluru, fair-play rule 01 | powernext-ai.in | **Confirmed** |
| Solution must work with datasets provided during hackathon | Problem PDF | Confirmed |
| Kaggle dataset link, files, columns, MOG_A = magnetic oil gauge indicator | Kaggle page / dataset description | **Confirmed** |
| Kaggle duplicates / conflicts / jumps | Public audit repo | Reported (verify on download) |
| CPRI's three failure causes | CPRI journal abstract | **Confirmed (abstract)** |
| IS 1180 %X limits 2% / 7.5% | CPRI Bhopal IS 1180:2014 deck | Confirmed from CPRI deck; verify vs standard |
| ~1.3 M DT failures/yr | CEA meeting, Mercom headline | Confirmed (reported headline) |
| ~10% rate, Kerala 1.9%, CESC 0.4–0.5%, Tata Power-DDL < 1%, CEA health-index proposal | Mercom, T&D India, Legality Simplified | **Reported** (consistent across outlets) |
| Moisture ingress = 90% of failures | Mercom subheading | Reported only — don't use |
| Tan-delta periodic testing recommended for DTs | T&D India coverage | Reported; verify |
| CIGRE JWG A2/D2.65 exists (twin definition, reality gap) | cigre.org ToR | **Confirmed** |
| ETT license | Repo LICENSE: CC BY-ND 4.0 (HF card says CC BY 4.0) | Follow repo file |
| DT metering ~42% (69% urban, 32% rural) | CEA metering report via Prayas | Reported |
| IEC 60076-7 reference life 180,000 h; DT temperature limits | Standard | To verify |

---

## 21. Open items & fallbacks

| # | Item | From | Fallback |
|---|---|---|---|
| 1 | Nameplate photo, dial photos, max load | Technicians | §3.1 placeholders |
| 2 | HV voltage | Technicians | 11 kV |
| 3 | Permission to download weather | User | Synthetic ambient |
| 4 | April 2026 window | User | April 2026 |
| 5 | Judging rubric, finale data format, whether judges run code, time limits | Organizers (team-lead email / vedclub.mit@manipal.edu) | PDF baseline; adapter handles format |
| 6 | Primary sources: IS 1180:2014, IEC 60076-7 | Library | Keep limits configurable, off slides |
| 7 | ETT LICENSE reading | Repo | Validation only or skip |
| 8 | Excel clarifications ("Rated" column, L-N vs L-L, rig location) | Organizers | Assumptions |
| 9 | Breathing type? | Technicians | Assume yes |
| 10 | Domain review (30 min) | Professor / DISCOM engineer | Peer review within team |

---

## 22. First actions
1. **P2:** Python 3.12 venv, install, smoke test with 1391 A amps.
2. **P1 + P3:** write `contracts/` and freeze with the team (hour 2).
3. **P1:** mock data + synonyms + Kaggle download.
4. **P4:** repo, app shell, email organizers.
5. **Everyone:** stubs with real interfaces by hour 2. Then build.
