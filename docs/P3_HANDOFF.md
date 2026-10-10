# P3 Intelligence: handoff note

Status: built and tested on mock data. Branch `p3-intelligence`. Contracts (`contracts/models.py`, `contracts/canonical.py`) are **drafts, not frozen**; nothing here has been agreed with P1, P2 or P4 yet.
Source of truth for design: `FINAL_PRD.md` sections 8 and 12. This note says what actually exists.

Tags: **[Confirmed]** tested here | **[Assumed]** our choice | **[To verify]** needs a primary source.

---

## 1. Run it
```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install pandas numpy scikit-learn pyyaml pytest
.venv\Scripts\python.exe -m pytest -q          # 157 passed (7 Kaggle tests skip if the data folder is missing)
.venv\Scripts\python.exe -m eval.run_eval      # lead-time + false-alarm table on MOCK data
```
Kaggle tests read `DT_KAGGLE_DIR` (default `C:\Apps\Power\dt-twin\data\raw\kaggle`) and skip when it is absent. The Kaggle files are third-party ("copyright-authors") and must never be committed.

## 2. The one call P4 needs
```python
from analytics.common import load_thresholds
from analytics.pipeline import analyze, StreamAnalyzer
from analytics import residual, health, through_fault

T = load_thresholds()                                   # config/thresholds.yaml
ref = residual.calibrate(normal_df, T)                  # once, from a Normal (fault-free) twin run
res = analyze(df_twin, events, caps, T, residual_reference=ref)   # batch
sa  = StreamAnalyzer(caps, T, residual_reference=ref)             # streaming (re-runs analyze on the buffer)
res = sa.update(twin_state, new_events)
```
`analyze()` returns `AnalysisResult(alerts, recommendations, health, rul, fidelity_rmse_C)`.
- `rul` is always `None`: RUL belongs to P2.
- `residual_reference` is the one extension to the PRD signature (optional). Without it the detector self-calibrates on the first 7 days of the data, which would hide a fault in week one.
- `StreamAnalyzer` is O(n) per update (O(n^2) per stream). Fine for demo replays, not for long runs.

Extra functions for dashboard charts:
| Need | Call |
|---|---|
| Health Index over time + sub-scores | `health.compute_series(df, alerts, caps, T)` -> columns `timestamp, score, band, thermal, ageing, loading, electrical, integrity, fault_stress, capped` |
| Through-fault log + cumulative stress | `through_fault.stress_table(events, T)` |
| Current unbalance % series | `electrical.unbalance_pct(df)` |
| Lead-time table (MOCK) | `docs/figures/lead_time_mock.csv` / `.md` |

## 3. What the pipeline expects as input
Trend columns follow `contracts/canonical.py` (draft) plus the twin columns from PRD 7.2: `twin_oil_C, twin_hs_C, aging_rate, days_aged_cum, residual_oil_C, fidelity_rmse_C, load_pu`. Events follow `EVENT_COLUMNS`. `caps` uses `CAPABILITY_KEYS`.
- Columns starting `gt_` or `alarm_` are stripped and the pipeline raises if any reach a detector.
- Missing or all-NaN channels switch a detector off; they never crash it. Detectors return `[]` for fewer than 2 rows.
- Meter-only mode (no `OTI_C`): rules fall back to `twin_oil_C`/`twin_hs_C` and say "twin-estimated"; the residual detector returns `[]`.
- `config/thresholds.yaml` has a `reference` block (`i_rated_a`, `v_ln_nominal_v`) that mirrors P2's `asset.yaml`. Remove it when `asset.yaml` exists. [Assumed]

## 4. What comes out
`Alert` fields are in `contracts/models.py`. Use them like this:
- Badge: `alert.simulated` -> SIMULATED badge. `alert.origin` is `asset` or `sensor` (sensor = "check the device, not the transformer").
- Group by `alert.module`: `overloading | insulation | short_circuit | electrical | oil | data`. (`moisture` is not emitted yet.)
- Alert types: `loading_high, overcurrent, hot_spot_high, top_oil_high, ageing_rate_high, residual_drift, current_unbalance, voltage_unbalance, voltage_high, voltage_low, oil_low, oil_leak, oil_theft, through_fault, through_fault_stress, jump_sensor, range_sensor, stuck_sensor, dead_channel`.
- Each alert has `recommendation_id`; look it up in `result.recommendations` (fields: `action, test, urgency, rationale, alert_id, standard_ref`). A `residual_drift` next to an oil alert gets a compound recommendation. Health band Red adds a tan-delta/insulation recommendation.
- `result.health`: `score, band, components, weights, capped`. `weights == {}` means no sub-score was available (score 100 by convention). `capped` is True only when the weakest-link cap actually lowered the score.

## 5. Module map
| File | Does |
|---|---|
| `analytics/rules.py` | Loading, overcurrent, top-oil, hot-spot, ageing-rate alarms with hysteresis |
| `analytics/residual.py` | Cooling-degradation detector on measured minus twin oil temperature, normalised by the twin's rise above ambient (load-robust) |
| `analytics/electrical.py` | Current/voltage unbalance, over/under voltage (no neutral or earthing claims) |
| `analytics/oil.py` | Low level, slow leak, sudden step (theft) |
| `analytics/through_fault.py` | Event-table stress tracker; recommends a short-circuit impedance (%X) test |
| `analytics/sensor_faults.py` | Jump, range, stuck, dead channel; relabels asset alerts caused by a bad sample to `origin="sensor"` |
| `analytics/health.py`, `config/health.yaml` | Health Index (six sub-scores, weights 30/25/15/15/10/5, cap at 40) |
| `analytics/recommend.py` | Alert -> named test and urgency |
| `analytics/pipeline.py` | `analyze()`, `StreamAnalyzer` |
| `eval/` | Lead time vs a plain-threshold baseline, false alarms |
| `tests/mock_data.py` | Labelled MOCK scenarios N, S1-S5 with ground truth. Not P2's generator |

## 6. Results so far (MOCK data only) [Confirmed by running]
| Fault | First alert vs onset | Plain-threshold baseline |
|---|---|---|
| Overload | at onset (rule) | fires at the same time: no lead |
| Cooling degradation | ~57.5 h after ramp start, oil at ~62 C (< 85 C warning) | **never fires** |
| Unbalance | at onset | same time: no lead |
| Oil leak | ~17 h after onset | **65 h later** |
| Oil theft | at onset | same time |
| Through-faults | at first event | cannot see them (event data only) |
False alarms: 0 in every scenario. **These prove the detectors on a stand-in dataset. They say nothing about real or P2-generated data.** The honest headline: the twin adds lead time on cooling degradation and slow leaks; for overload, unbalance and theft a plain threshold does as well.

## 7. Known limitations and open decisions
1. **Oil detector on the real Kaggle data.** `OLI` there is bimodal (about 44% of samples at 100, about 49% below 85, quantiles 37-42 at the low end) with 75 drops of 8+ points and 59 rises. Before the fix the detector raised 107 `oil_theft` alerts. Of the 75 drops, 33 lasted at least 1 h and **all 33 recovered within 24 h**; oil does not refill itself, so these are gauge or thermal behaviour. Fixed: a theft step must persist for `THEFT_PERSIST_H` (1 h) and not recover for `THEFT_RECOVERY_H` (24 h). Result on Kaggle: 0 `oil_theft`. **Still raised: 31 `oil_low` and 9 `oil_leak`.** `oil_low` is technically correct against the 85% limit (the reported level is below it about half the time), but the channel itself looks unreliable, so do not present those as findings. A theft alert now appears 1 h after the step and is withdrawn if the level returns within 24 h (a streaming consumer will see it come and go). [Confirmed by running]
2. **Stuck-sensor rule over-fires on quantised data:** 93 alerts on Kaggle (1 C resolution, slow lag). Untuned.
3. **Voltage sags on Kaggle are flagged as sensor faults** (range < 100 V) but look like real supply events. The spec's 100 V rule can mislabel a supply fault as a device fault.
4. **Kaggle through-fault, residual, electrical** detectors do not run on it (no twin, no caps).
5. **Residual detector:** `MIN_RISE_C = 10` and the normalisation were tested on one mock seed where the mismatch is exactly proportional to the rise. A fixed offset (e.g. a mis-calibrated sensor) is seen less at high load. Old-style references (without `rel_*` keys) fall back to the old, load-sensitive absolute test: re-calibrate.
6. **Health Index mapping is our design** (PRD gives none). Every parameter in `config/health.yaml` is [Assumed]. The weakest-link cap uses a 24 h window because alerts only carry a start time. Through-fault stress never resets.
7. **Constants not in `thresholds.yaml`** (named defaults in code): ageing alarm at 1 h mean rate >= 1.0; leak = 3 points over 24 h; thermal-cause delta 5 C; residual episode merge 24 h; self-reference 7 days; jump/range/stuck/dead parameters in `sensor_faults.py`.
8. **Not built:** IsolationForest, breathing-stress index, ATI-vs-weather check, V/I consistency check, neutral-current measurement (Kaggle has `INUT`, the pipeline does not yet use it).
9. **IS 1180 limits, tan-delta as a CEA recommendation, IEC 60076-7 limits** are [To verify]; recommendation text says so and never states numeric limits.
10. The thresholds file is the PRD section 9 defaults, all [Assumed].

## 7a. Concerns (advisor notes, please read before relying on these results)
1. **Every performance number is from a stand-in dataset I wrote.** The mock thermal model is a simplified first-order model with a deliberate 3% parameter mismatch. Real transformers will behave differently. Treat the lead-time table as a unit test, not evidence.
2. **The twin adds lead time on only two of six faults.** Cooling degradation and the slow oil leak. For overload, unbalance and theft a plain threshold alarms at the same moment. Do not overclaim "AI detects faults earlier".
3. **Some detectors were tuned after inspecting the real Kaggle data.** The oil theft persistence rule, the sensor-fault load-step excuse and the range limits were adjusted once glitches were seen. Passing that data afterwards is not an independent test. Evaluate on a second unit or a held-out period before quoting a result.
4. **The theft rule can miss a real theft followed by a refill within 24 h,** and it makes a theft alert appear 1 h late and disappear if the level recovers (visible to streaming consumers). That trade-off is a design decision made on one unit's data.
5. **The load-robust residual was tested on one mock seed where the mismatch is exactly proportional to the rise.** That is the case it handles best. Fixed temperature offsets are seen less at high load. `MIN_RISE_C = 10` is a judgement call (raising it to 20 C cost about 5 h of lead on S2).
6. **The Health Index has no ground truth.** Weights, curves, the 40-point cap and the 24 h cap window are our own choices. It is explainable sub-score by sub-score, but not validated. State that it is a transparent engineering score.
7. **The Kaggle unit is a different, unrated transformer** with a bimodal oil gauge, a dead winding-temperature channel and heavy duplicate timestamps. Findings on it say something about data quality, not about Transformer-1.
8. **Several recommendation rows have no basis in the PRD** (voltage alerts) and some standards references are secondary-source only (tan-delta as a CEA recommendation, IS 1180 limits). They are marked "to verify" in the text. Do not print numeric limits on a slide until the standard text has been read.
9. **`StreamAnalyzer` re-runs the whole analysis on every row** (O(n^2) over a stream). Fine for a 30-day replay at demo speed; it will not scale to live data without incremental detectors.
10. **Nothing here has been reviewed by a domain expert.** The 30-minute review in the PRD open items (item 10) is still outstanding and is the largest remaining risk.
11. **Contracts are drafts nobody else has agreed to.** `analyze()` has an extra optional argument. Integration work from other roles may require changes here.

## 8. What P1 and P2 must provide
- **P2:** twin columns named as in section 3; a Normal run for `residual.calibrate`; the asset block replacing `thresholds["reference"]`. Soften scenario S1: with placeholder losses the PRD's 1.15-1.35 pu overload drives the hot spot to ~150 C and the ageing rate to ~550x, which a domain judge would find implausible.
- **P1:** cleaned canonical data with `dq_flags`; `tests/kaggle_loader.py` is a stand-in until the adapter exists.
- **All four:** agree `contracts/*` before anything depends on it. The optional `residual_reference` argument is a signature extension that needs agreement.
