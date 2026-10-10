# Assumptions register (data layer)

Companion to FINAL_PRD.md §19. Every entry says what we chose, why, and where it lives in code/config.
Tags follow the PRD legend: **[Assumed]** our choice · **[Confirmed]** checked by us · **[Open]** unresolved.

## Scenario design (generated campus data, SIMULATED)

**A1. Normal-scenario load was tuned so it does not trip our own alarms.** [Assumed — scenario-design choice]
- `config/scenarios.yaml`: weekday peak **0.55–0.70 pu** (first draft 0.55–0.75), ambient coupling
  **0.004 pu/°C** above 28 °C (first draft 0.006).
- Why: with the first draft, Normal peaked at 0.83 pu and a 100.8 °C hot-spot, above the 98 °C warning. A
  "Normal" month with a hot-spot warning can't serve as the false-alarm baseline (PRD §11).
- Honest caveat: we adjusted the synthetic input until it stopped triggering thresholds we also wrote. That is a
  scenario-design choice, not evidence that the detectors are quiet on real healthy units. 0.55–0.70 pu is a
  realistic campus weekday peak, but the false-alarm rate on Normal says nothing beyond that. Real-data false
  alarms are measured on Kaggle (PRD §11).

**A2. S1 overload softened to 1.10–1.25 pu, short daytime windows.** [Assumed]
- PRD §5.2 asked for 1.15–1.35 pu for 6–10 h/day. With the library's ONAN defaults (60 K rated top-oil rise,
  +10 K ambient surcharge) and April afternoon ambient (~35 °C), that gave a **171 °C hot-spot**, which isn't believable.
- Now: day 24 at 1.10 pu for 3 h, day 25 at 1.18 pu for 2 h, day 26 at 1.25 pu for 1.5 h, centred at 13:00.
  The hot-spot crosses the 98 °C warning every day and peaks at **121 °C**, above 115 °C for 1 h.
- Days 25–26 are a weekend in April 2026 (kept PRD's day numbers).

**A3. Through-faults, unbalance, leak, theft magnitudes** as in `config/scenarios.yaml`. [Assumed]

## Data-quality rules (where code deviates from the first spec text; spec now updated)

**A4. Ambient (ATI) is excluded from the stuck-sensor check.** [Assumed]
- Spec rule: STUCK = unchanged ≥ 8 samples *while load changes > 10 %*. Ambient doesn't depend on load, so the
  rule says nothing about an ambient sensor. On Kaggle (1 °C resolution) it flagged 5,512 of 17,104 rows.
- Ambient is checked against weather instead (`ATI_MISMATCH`). Code: `ingest/validate.py STUCK_COLS`.

**A5. Jumps are measured over at least 15 minutes.** [Assumed]
- Rate = |Δ| ÷ max(Δt, 15 min) × 15 min, and never across a GAP. Otherwise a 1 °C step between two 1-minute
  samples counts as 15 °C/15 min. The Kaggle 1-minute bursts gave 212 such "jumps" against 47 real ones.
  Code: `ingest/validate.py`.

**A6. Temperature reading of exactly 0.0 counts as a dropout (RANGE flag)** when the channel's median is
above 5 °C. [Assumed] Code: `ingest/validate.py`.

## Kaggle (real field data, different transformer)

**A7. Date range 2019-07-01 → 2020-03-24 (Asia/Kolkata).** [Assumed — see data/PROVENANCE.md §1.6]
- Before: not energised (zero current on all June rows, OTI = ATI, energy counter frozen).
- After: load regime change from 2020-03-25 (evening peak −33 %), only 20 days and after a 14-day gap.
- Logging gaps inside the range are kept and flagged `GAP`. The energy counter proves it is one asset throughout.

**A8. Kaggle `WTI` is a 0/1 flag, not a winding temperature.** [Confirmed by inspection]
- Values are only 0 and 1 (0.5 appears only where duplicates were median-merged). It is mapped to `alarm_WTI`,
  display only. The auto-mapper rejects it as a temperature because binary values are implausible for an analog channel.

**A9. Kaggle timestamps are local time (Asia/Kolkata).** [Assumed] Supported by the 18–19 h evening load peak.

**A10. Kaggle rating estimated from data: 214.7 A ≈ 155 kVA** (p99 I_mean / 0.8, spec §2.7). [Assumed — estimated]

**A12. No twin is fitted to the Kaggle unit; a physics plausibility check replaces it** (PRD §7.4). [Assumed — design decision]
- Band parameters: low = 30 K rated rise, R = 10, no surcharge; high = 60 K, R = 4, +10 K surcharge; x = 0.8;
  tolerance 2 K; channel suspect if > 50 % of evaluable rows fall outside. The 30 K low edge leans on IS 1180's
  35 K top-oil limit [To verify against the standard text].

**A13. Kaggle location: Hyderabad.** [Assumed] ATI fits Hyderabad weather (daily corr 0.63) far better than Bengaluru (0.27).

## Twin engine

**A14. Actual ageing uses measured top-oil + the twin's winding gradient** (IEC 60076-7 practice), per row, only where
the OTI channel has passed the plausibility check so far (causal: ≥ 96 evaluable rows, ≤ 50 % outside the band), the
row has no sensor-fault flag (RANGE/JUMP/STUCK OTI or ATI) and its rise is **not below** the physics band. Otherwise the
twin hot-spot is used. A rise *above* the band is kept on measured: it may be a real asset fault (S2 cooling runs
hotter than any healthy design), and falling back there would hide the fault's cost. [Assumed]
Both are reported: expected (twin, healthy cooling) and actual; RUL uses actual. On Normal, actual is ~11 % below
expected because the generated plant is deliberately slightly cooler than the nominal twin.

**A15. RUL display capped at "> 40 years"**; the raw value (numeric guard 1000 y) stays in reports. Primary figures on the
dashboard are life consumed in the period (days, expected vs actual) and the ageing rate. [Assumed]

**A16. Snapshot mode treats each record as a steady state** (library steady-state functions, no time constants).
Valid for real steady-state test records (e.g. heat-run results). On data that is really a time series with the
time removed (fixture F15r), thermal lag makes the residual spread wide (±7 K, 7 % of records outside the physics band)
— use `interval=` for such files. Missing ambient in snapshot mode = median of the file's valid ATI, else 27 °C,
flagged ASSUMED_AMBIENT. Duplicate measurement pairs are flagged but both records kept (they have distinct IDs). [Assumed]

## Analytics integration (p3-intelligence merged into main)

**A17. A temperature step that a load step explains is physics, not a sensor jump.** [Assumed] At ingestion, JUMP_OTI /
JUMP_WTI are not raised when the load moved > 25 % within the preceding 3 h (one oil time constant), unless the step
exceeds the whole rated rise (60 K). In the analytics jump check, a step the twin also makes (same channel) is excused.
Why: in S1 the winding hot-spot genuinely rises 8 °C in 15 min (4 min winding constant) and top-oil ~5 °C/15 min at a
0.42 → 1.18 pu step; both were being reported as sensor faults and relabelled real overload alarms. Kaggle's 245 °C
plateaus remain flagged (> 60 K, and RANGE).

**A18. Untrustworthy channels are hidden from asset detectors, not from the sensor layer.** [Assumed] A top-oil channel
that fails the plausibility check (caps `residual_fidelity` False) and an oil-level channel that drifts (rises ≥ 10 points
over 21 days with no refill step) or is stuck on > 50 % of rows are dropped before the asset detectors run; the sensor
layer still sees them and raises `implausible_sensor` / `drift_sensor` / `stuck_sensor`. The residual detector is off
when `residual_fidelity` is False. Result on Kaggle: no residual alerts, no oil alerts, no top-oil alarm from measured OTI.

**A19. Alerts computed from the twin's estimate are never relabelled as sensor faults** (a flagged measured channel
didn't produce them). On Kaggle one `top_oil_high` remains, twin-estimated at the *estimated* rating with placeholder
losses: indicative only.

**A20. One slow leak = one alert:** leak episodes closer than 48 h are merged (the oil level follows the daily
temperature cycle, so the 24 h decline dips under the clear level at night). [Assumed]

**A21. Residual threshold re-tuned on the real Normal scenario: kept at mean + 4σ, persistent 2 h** (load-normalised).
Sweep (calibrated on seed 0, tested on unseen seeds 1–3 with different plant parameters): 3σ and 3.5σ/≤2 h give false
alarms on Normal; 4σ/2 h gives 0 false alarms on N seeds 1–3 and on S1, and detects S2 after 57 / 40 / 28.5 / 56 h
(seeds 0–3). 3.5σ/4 h is also quiet but sits at the edge for little gain. [Assumed]

**A22. Ageing in health and the ageing-rate alarm use actual ageing** (`aging_rate_actual`) when present, so the cost of
a cooling fault counts. S2's top-oil / hot-spot / ageing alerts are consequences of the fault and count as true positives.

**A23. Snapshot records get a per-record Health Index at their operating point** (`analytics.pipeline.analyze_snapshot`,
same curves/weights, each record scored alone), ranked worst first. Time-based detectors don't apply.

## Real-data tuning (Kaggle) — one alert per condition

**A24. Electrical alerts use a 1 h median, ignore current unbalance below 0.05 pu load, and merge episodes < 24 h
apart.** [Assumed] The Kaggle unit's phases are chronically unbalanced (median 25 %); per-sample hysteresis made
2,042 alerts. Now 5 (one per real episode). Cost: on generated S3 the alert comes 30 min after onset instead of at
onset. Voltage high/low/unbalance get the same treatment (voltage low 41 → 4).

**A25. A temperature channel is "stuck" only if flat for ≥ 6 h (two oil time constants) while the twin says it
should have moved ≥ 2 °C; stuck periods on a channel < 24 h apart are merged.** [Assumed] The spec's 8 samples (2 h)
flagged a 1 °C-resolution sensor that sits near ambient (86 OTI alerts → 0; the channel is reported as implausible
instead). The saturated oil gauge: 302 → 18 (one per data segment).

**A26. The analytics jump limit never drops below 5 °C** (same rule as A5 at ingestion). Scaling 5 °C/15 min to a
1-minute gap gave a 0.33 °C limit, so every 1 °C tick was a "jump" (86 → 16, all real ≥ 6 °C steps).

**A27. With a rating estimated from data (no nameplate), rating-dependent alerts are indicative only**: loading,
over-current, hot-spot, top-oil and ageing-rate alerts become severity `info` with a note, so they are shown but
never counted as findings or used for the Health Index cap. Measured conditions (unbalance, voltage) and all sensor
faults keep their severity. Kaggle: 2,648 alerts → 133 (95 findings: 79 sensor, 16 electrical; 38 indicative);
Health Index 40 Red → 82 Green. Generated scenarios: still 0 false alarms, lead times unchanged.

## Thermal profile (dashboard physics, twin/profile.py)

**A28. Bottom-oil rise = 0.5 × top-oil rise** (ONAN typical for the IEC 60076-7 thermal diagram), so
θb = θa + 0.5·(θo − θa). Average oil = (θo + θb)/2; average winding = average oil + gr·K^y. Shown as est. [Assumed]

**A29. Oil flow intensity ∝ Q^(1−x)**: in ONAN the thermosiphon flow is Q/(c·ΔT_bottom→top) and ΔT grows as Q^x,
so flow grows as Q^(1−x). Normalised to 1 at 1.4 pu (top of the what-if range), clipped to 0–1. Visual only. [Assumed]

**A30. Radiator effectiveness k = (Δθo,twin/Δθo,measured)^(1/x)**: the share of nominal cooling that explains the
measured rise at the same losses, 6 h rolling median, only where measured OTI drives ageing (A14) and the twin rise is
≥ 5 K. Normal ≈ 1.04 (the generated plant is slightly cooler than the nominal twin); S2 falls to ≈ 0.82 after the
cooling fault. A quasi-steady estimate: it lags real changes by about τo. [Assumed]

**A31. Heat to air = (P0 + Pk)·(Δθo/Δθor)^(1/x)**, the inverse of the steady-state top-oil law using the twin's present
rise; stored heat = losses − heat to air. It is exact at steady state (tested) and a first-order estimate in
transients. Losses use the placeholder nameplate values (asset.yaml). [Assumed]

**A32. What-if cooling effectiveness k scales the top-oil rise by k^(−x)** (the inverse of A30), leaving the winding
gradient unchanged (it does not depend on the radiators). The approach curve uses the IEC 60076-7 exponential
equations with the library's k11 = k21 = 1 (no winding overshoot term). Time to steady state: until top-oil and
gradient are within 1 K. [Assumed]

## Weather

**A11. Site point for Transformer-1 weather: Bengaluru city (12.97 N, 77.59 E)**, Open-Meteo archive, cached
offline. The campus coordinates were not used. [Assumed]

## Generic profile, physics and outlook (added with the generic-transformer work)

**A24. Unknown-unit defaults.** [Assumed] Rating and voltage are enough to run. Missing losses use 10 W/kVA (load) and
1.1 W/kVA (no-load); missing thermal parameters use the IEC 60076-7 distribution-transformer defaults. Every value is tagged
and a nameplate value always wins. The profile page shows which values are defaults.

**A25. Loss split from two totals.** [Derived] Where a nameplate gives total losses at 100 % and 50 % load, load loss is
`(T100 - T50) / 0.75` and no-load loss is `T100 - load loss`, assuming load loss scales with load squared and both totals
are at the same temperature. To be verified against the datasheet.

**A26. Winding rise on a nameplate is recorded but not used** by the thermal model: mapping an average winding rise to the
winding-to-oil gradient needs an assumption the standard does not fix.

**A27. Detailed heat-balance model constants.** [Assumed, To verify] Loss split 88 % I2R / 8 % eddy / 4 % stray of load
loss; copper temperature constant 234.5 K; oil viscosity law `exp(2797.3 / (theta + 273))`; the winding-to-oil gradient scales
with viscosity^(1/4); the cooling law uses the profile's exponent x. The thermal capacity is set so the small-signal oil time
constant equals the profile's. Masses from a nameplate give an optional, upper-bound time constant (assumed specific heats and
a 30 % tank / 70 % core-and-coil split of the dry mass).

**A28. Residual baseline per transformer.** [Assumed] For any rated profile the residual detector's healthy baseline is the
generator's Normal month for that asset, run through the twin (seed 0). When only an estimated rating is known the detector
self-calibrates on the first week instead. A real unit whose model error is larger than the generator's +-4 % parameter
perturbation could trigger false residual alerts.

**A29. Outlook limits and draws.** [Assumed] Headroom and time-to-limit use top oil 95 C and hot spot 120 C (the critical
thresholds). The Monte Carlo remaining life draws load level (log-normal sigma 0.08), ambient shift (sigma 2 K), load growth
(N(2 %, 1.5 %) a year), cooling factor from the recent residual (1.0 to 1.6), ageing-model uncertainty (log-normal sigma 0.25),
and initial-life uncertainty (sigma 5 % of the reference life), over a 60-year horizon. The reference life is 180,000 h
[To verify].

**A30. Diagnosis ramps and advice schedule.** [Assumed] Evidence ramps are in `analytics/brief.py` and `docs/METHODOLOGY.md`;
a sustained condition with evidence of 0.4 or more raises the status to "watch" even when the alert that first flagged it is
older than 24 h. Advice priority follows the most urgent recommendation linked to active alerts, with 7 days as the default
when only a diagnosis (no alert) is active.
