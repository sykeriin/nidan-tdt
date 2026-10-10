MOCK DATA, simulated: results below prove the detectors on a stand-in dataset, not on real or P2-generated data.

## Lead time per injected fault

| scenario | fault | gt_onset | detected | first_alert_ts | first_alert_type | baseline_rule | baseline_ts | lead_vs_baseline_h | lead_vs_onset_h | detector |
|---|---|---|---|---|---|---|---|---|---|---|
| S1 | overload | 2026-04-25 08:00 | True | 2026-04-25 08:00 | loading_high | loading_alarm | 2026-04-25 08:00 | 0.00 | 0.00 | rule |
| S2 | cooling_degradation | 2026-04-21 00:00 | True | 2026-04-23 09:30 | residual_drift | top_oil_warning (never crossed) | none | none | -57.50 | residual |
| S3 | unbalance | 2026-04-26 00:00 | True | 2026-04-26 00:00 | current_unbalance | unbalance_warning | 2026-04-26 00:00 | 0.00 | 0.00 | rule |
| S4 | oil_leak | 2026-04-21 00:00 | True | 2026-04-21 16:45 | oil_leak | oil_level_low | 2026-04-24 10:00 | 65.25 | -16.75 | rule |
| S4 | oil_theft | 2026-04-28 02:30 | True | 2026-04-28 02:30 | oil_theft | oil_level_low | 2026-04-28 02:30 | 0.00 | 0.00 | rule |
| S5 | through_fault | 2026-04-28 10:14 | True | 2026-04-28 10:14 | through_fault | none | none | none | 0.00 | rule |

Positive lead_vs_baseline_h: the twin alerted before the plain threshold. 'none' in baseline_ts means the plain threshold never alarmed, so there is no lead number to quote. Negative lead_vs_onset_h: detected after onset.

## False alarms (warning/critical alerts matching no injected fault)

| scenario | false alarms | true positives | alerts/week | by type |
|---|---|---|---|---|
| N | 0 | 0 | 0.00 | none |
| S1 | 0 | 21 | 0.00 | none |
| S2 | 0 | 1 | 0.00 | none |
| S3 | 0 | 2 | 0.00 | none |
| S4 | 0 | 3 | 0.00 | none |
| S5 | 0 | 4 | 0.00 | none |
