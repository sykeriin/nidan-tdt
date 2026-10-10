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

## Weather

**A11. Site point for Transformer-1 weather: Bengaluru city (12.97 N, 77.59 E)**, Open-Meteo archive, cached
offline. The campus coordinates were not used. [Assumed]
