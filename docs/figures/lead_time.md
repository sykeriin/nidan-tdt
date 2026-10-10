SIMULATED: generated campus data for Transformer-1 (sim/generator.py, seed 0), measured through the adapter, the nominal twin and the analytics pipeline. The plant is deliberately different from the twin. These numbers test the detectors on synthetic faults; they are not field evidence.

## Lead time per injected fault

| scenario | fault | gt_onset | detected | first_alert_ts | first_alert_type | baseline_rule | baseline_ts | lead_vs_baseline_h | lead_vs_onset_h | detector |
|---|---|---|---|---|---|---|---|---|---|---|
| N | none (Normal) | none | False | none | none | none | none | none | none | none |
| S1 | overload | 2026-04-24 11:30 | True | 2026-04-24 12:00 | loading_high | loading_alarm | 2026-04-24 12:00 | 0.00 | -0.50 | rule |
| S2 | cooling_degradation | 2026-04-20 00:00 | True | 2026-04-22 09:00 | residual_drift | top_oil_warning | 2026-04-27 15:00 | 126.00 | -57.00 | residual |
| S3 | unbalance | 2026-04-25 00:00 | True | 2026-04-25 00:30 | current_unbalance | unbalance_warning | 2026-04-25 00:00 | -0.50 | -0.50 | rule |
| S4a | oil_leak | 2026-04-21 06:00 | True | 2026-04-21 22:45 | oil_leak | oil_level_low | 2026-04-23 22:00 | 47.25 | -16.75 | rule |
| S4b | oil_theft | 2026-04-25 02:15 | True | 2026-04-25 02:30 | oil_low | oil_level_low | 2026-04-25 02:30 | 0.00 | -0.25 | rule |
| S5 | through_fault | 2026-04-27 10:12 | True | 2026-04-27 10:12 | through_fault | none | none | none | 0.00 | rule |

Positive lead_vs_baseline_h: the twin/analytics alerted before the plain threshold. 'none' in baseline_ts means the plain threshold never alarmed. lead_vs_onset_h is measured against the ground-truth onset; negative = detected after onset. Overload, unbalance and theft are caught at the same moment as a plain threshold: the twin adds lead on cooling degradation and the slow leak.

## False alarms (warning/critical alerts matching no injected fault)

| scenario | false alarms | true positives | alerts/week | by type |
|---|---|---|---|---|
| N | 0 | 0 | 0.00 | none |
| S1 | 0 | 12 | 0.00 | none |
| S2 | 0 | 6 | 0.00 | none |
| S3 | 0 | 1 | 0.00 | none |
| S4a | 0 | 2 | 0.00 | none |
| S4b | 0 | 2 | 0.00 | none |
| S5 | 0 | 4 | 0.00 | none |
