# Methodology

Every formula below is implemented in the module named beside it. Values marked **[Assumed]** are engineering choices
(listed in `assumptions.md`); values marked **[To verify]** should be checked against the primary standard before they
appear on a slide. Nothing here is fitted to data.

## 1. The transformer profile (`twin/profile.py`)

A profile is any subset of nameplate numbers; the rating (kVA) or the rated current is required.

- Rated current (LV): `I_rated = S / (√3 · V_LL)` [Calculated].
- Losses: given directly, or solved from the maximum total losses at 100 % and 50 % load, assuming load loss scales with load squared:
  `P_load = (T₁₀₀ − T₅₀) / 0.75`, `P_no-load = T₁₀₀ − P_load` [Derived]. Otherwise a typical 10 W/kVA load loss and 1.1 W/kVA no-load loss [Assumed].
- Thermal parameters not on the nameplate take the IEC 60076-7 distribution-transformer defaults: top-oil rise 60 K, ambient surcharge 10 K, winding-to-oil gradient 23 K, hot-spot factor 1.2, oil time constant 180 min, winding time constant 4 min, exponents x = 0.8 and y = 1.6.
- Every value carries a source tag. A nameplate value always beats a default.

## 2. Thermal model (`twin/thermal.py`, `twin/engine.py`, `twin/physics.py`)

With `K = I / I_rated` and `R = P_load / P_no-load`, the IEC 60076-7 steady state is

```
Δθ_o  = (Δθ_or + Δθ_sur) · ((1 + R·K²) / (1 + R))^x          top-oil rise over ambient
Δθ_h  = H · g_r · K^y                                         hot-spot rise over top oil
θ_h   = θ_a + Δθ_o + Δθ_h                                     hot-spot temperature
```

The dynamic response is the library's implementation of the IEC differential-equation method: the oil follows its steady
value through a first-order lag with the oil time constant; the hot-spot rise is the fast winding term (4 min) minus a slow
oil term. Load is passed to the library in **amps** (per-unit would be silently misread). Long gaps restart the model from steady state.
The Physics page shows the steady-state chain with the profile's numbers and checks it against the library (agreement to within 0.01 K).

Per sample the engine outputs the twin's oil and hot-spot temperatures, the residual `OTI − twin oil`, a rolling 24 h
RMSE (fidelity), the ageing rates and the plausibility band.

## 3. Ageing and remaining life (`twin/ageing.py`, `twin/rul.py`)

Relative ageing rate for normal Kraft paper: `V = 2^((θ_h − 98) / 6)` (V = 1 at 98 °C; 110 °C is the reference for thermally upgraded paper). Equivalent
days aged over a period are `Σ V·Δt / 24 h`. Two figures are kept: **expected** (the healthy twin's hot spot) and **actual** (measured oil
plus the twin's winding gradient, used only where the oil sensor has passed the plausibility check). The gap between them is the life a fault cost.

The Physics page also draws the Arrhenius law beside the 6 K rule (activation energies 111 kJ/mol and the value that matches the rule at 98 °C). They agree
near 98 °C and diverge away from it [To verify the activation energy for the paper in use].

## 4. Physics plausibility check (`twin/plausibility.py`)

Before a temperature channel drives anything, the library is run on the measured load and ambient for three plausible parameter sets (a cool low-rise design, the defaults, a hot
high-rise design). Rows where the measured oil-minus-ambient is more than 2 K outside that band are flagged `IMPLAUSIBLE_RISE`; a channel with more than half its rows outside is "suspect"
and is excluded from the residual detector and from measured ageing. On the Kaggle field data the oil sensor reads about 2 K above ambient at about a third of load, which no oil-filled
transformer can show; fitting a twin to it would have learned a meaningless rise. The ambient channel is also compared with cached weather.

## 5. A second model: heat balance with real losses (`twin/detailed.py`)

```
C · dθ_oil/dt = P_total(θ_w, K, V) − P_rated · (Δθ / Δθ_rated)^(1/x)
P_total = P_core·V² + P_I2R·K²·(T_w+234.5)/(T_w,R+234.5) + (P_eddy + P_stray)·K²·KF·(T_w,R+234.5)/(T_w+234.5)
hot-spot rise: first-order lag (winding time constant) to  H · g_r · K^y · (ν(θ_oil)/ν_rated)^(1/4),   ν ∝ exp(2797.3 / (θ + 273))
```

At rated load and rated ambient it equals the IEC result exactly. Elsewhere it differs for physical reasons: the cooling law is nonlinear, winding copper loss rises with temperature while
eddy and stray loss fall, harmonic currents (K-factor KF) add eddy loss, and cold, viscous oil widens the winding-to-oil gradient. The loss split (88 % I²R, 8 % eddy, 4 % stray of load loss),
the viscosity constant and the exponents are textbook or modelling choices [Assumed, To verify]. The thermal capacity is set so the small-signal oil time constant matches the profile's, or
(optionally) taken from the nameplate masses, which gives an upper bound.

The generator can run this model as the "real" transformer. The twin (IEC) then faces a structurally different plant, and the self-test reports the resulting error and detection results.

## 6. Anomaly detection (`analytics/`)

- **Rules with hysteresis** (`rules.py`): loading, overcurrent, top oil, hot spot and ageing rate against the thresholds in `config/thresholds.yaml` [Assumed]. The 60 °C bench trip from the organizers' sheet is not an operating alarm: a normal unit runs near 67 °C in Bengaluru.
- **Residual detector** (`residual.py`): the residual normalised by the twin's rise above ambient, `(OTI − twin) / (twin − ambient)`, so it holds across load. Threshold = baseline mean + 4σ from the healthy month generated for this transformer, persistent for 2 h [Assumed]. It sees a cooling fault days before any absolute limit.
- **Sensor versus asset** (`sensor_faults.py`): jumps faster than the oil can move (excused when the twin predicts them), out-of-range values, stuck readings, dead channels, a drifting oil gauge. Sensor-origin alerts say "check the device, not the transformer" and never colour a part of the 3D model red.
- **Oil** (`oil.py`): a slow slope is a leak; a step within an hour with no thermal cause that does not recover within 24 h is possible theft or tampering.
- **Electrical** (`electrical.py`): current and voltage unbalance (`max |x − mean| / mean`) and over/under-voltage.
- **Through-faults** (`through_fault.py`): from an event log, because 15-minute averages cannot show a short circuit; stress accumulates as I²t.

## 7. Health Index (`analytics/health.py`)

Six sub-scores (thermal 30, ageing 25, loading 15, electrical quality 15, integrity 10, fault stress 5 [Assumed]) from a shared piecewise-linear curve (100 at 80 % of the warning level, 70 at warning, 30 at critical, 0 beyond),
renormalised over the sub-scores the data supports. A critical asset alarm in the last 24 h caps the index at 40. Bands: green 80 and above, yellow 60 to 79, red below 60. This is a transparent engineering score, not a trained model.

## 8. Diagnosis and maintenance advice (`analytics/brief.py`)

For each fault class an evidence score between 0 and 1 is the larger of a smooth ramp over a measured quantity and a weight on active alerts:

| Class | Evidence from |
|---|---|
| Cooling degradation | residual as a share of the twin's rise (ramp 3 % to 12 %), `residual_drift` alert |
| Overload | peak load in the last 24 h (ramp 0.9 to 1.25 pu), hot spot (98 to 120 °C), overload alerts; halved when the oil is hot at normal load |
| Voltage excursion | deviation from nominal (ramp 4 % to 10 %), voltage alerts |
| Phase unbalance | current unbalance (ramp 8 % to 22 %), unbalance alerts |
| Through-fault stress | through-fault events and stress alerts in the last week |
| Oil loss | oil-level fall (ramp 3 to 12 points) and oil alerts; discounted when the gauge itself is flagged as faulty |
| Sensor or data fault | number of sensor-origin alerts in the last 24 h |

Shares are each class's evidence over the total; classes whose channel is missing are reported as "not observable with these inputs". Maintenance guidance maps the highest-urgency recommendation linked to active alerts
(or a class default from the PRD table) to a priority and schedule. These ramps are engineering judgement; the self-test reports how often the injected fault is ranked first.

## 9. Looking ahead (`twin/forecast.py`)

- **Headroom:** the largest steady load whose top oil stays within 95 °C and hot spot within 120 °C at the present ambient, found by bisection [limits Assumed].
- **Time to a limit:** `t = −τ · ln((target − ultimate) / (now − ultimate))`, exact for a first-order lag at constant load; "not reached" when the steady oil temperature stays below the target.
- **24 h forecast:** load and ambient are the hour-of-day means of the last 7 days (seasonal naive), run through the model after a 24 h run-in on the real data. The band is the 10th to 90th percentile of the twin's own recent errors against the measured oil temperature (or ±2 K, stated, when there is no sensor).
- **Remaining insulation life:** a 500-run Monte Carlo, seeded per dataset. Draws: load level (±8 %), ambient shift (±2 K), load growth (2 % a year ± 1.5), a cooling factor from the twin's recent residual, ±25 % ageing-model uncertainty and ±5 % initial-life uncertainty. The reference life is 180,000 h [To verify against IEC 60076-7]. Output is P10, P50 and P90 and a fan chart of life used over 40 years.
- **30-day limit risk:** the share of 400 simulated months (the recent diurnal pattern with day-to-day variation) in which the top oil or hot spot reaches its limit.

## 10. Limits, stated plainly

- Thermal ageing only: no moisture, partial-discharge or dissolved-gas information; no breakdown-date claims. Remaining life is a model outcome for the insulation if present conditions persist, not a field-validated failure forecast.
- Defaults for an unknown unit are assumptions. A nameplate beats them, and the profile page shows which is which.
- Scenario results are on synthetic data (including the detailed-model plant, which is itself a model). They are regression evidence, not field performance. There is no heat-run test data yet to validate the thermal model against.
- No machine-learning detector is included. An Isolation Forest second opinion was tried and left out: trained on one healthy month it flagged unusual load patterns in other healthy months and detected almost none of the injected faults.
- Thresholds, Health Index weights and diagnosis ramps are engineering judgement. IS 1180 and IEC 60076-7 limits are marked [To verify] and are configurable.
