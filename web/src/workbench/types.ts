// Shapes of the endpoints that return free-form JSON (brief, outlook, detailed physics). The server builds these in
// analytics/brief.py, twin/forecast.py and twin/physics.py.

export interface Diagnosis {
  fault: string
  label: string
  evidence: number
  share: number
  observable: boolean
  why: string
}

export interface WorkAction {
  action: string
  test: string | null
  urgency: 'immediate' | '24h' | '7d' | 'next_scheduled'
  why: string
  standard_ref: string | null
  alert_id: string | null
  alert_type: string
}

export interface Advice {
  priority: 'Immediate' | 'Urgent' | 'Soon' | 'Routine'
  schedule: string
  urgency: string
  actions: WorkAction[]
  note: string
}

export interface Brief {
  t?: string
  level: 'good' | 'watch' | 'critical' | 'nodata'
  sentence: string
  health?: { score: number | null; band: string | null }
  diagnosis: Diagnosis[]
  advice: Advice | null
  kpis: {
    headroom?: { pu: number; limiting: string | null; ambient_C: number }
    time_to_limit?: { status: 'not_reached' | 'reaches_limit' | 'already_reached'; hours: number | null; steady_state_oil_C?: number; target_oil_C?: number }
    ageing_rate?: number | null
    residual_pct?: number | null
    unbalance_pct?: number | null
  }
}

export interface RulFan {
  years_p10: number
  years_p50: number
  years_p90: number
  risk: string
  censored_fraction: number
  horizon_years: number
  fan: { years: number[]; p10: number[]; p50: number[]; p90: number[] }
  inputs: { consumed_life_pct: number; cooling_factor: number; runs: number; reference_life_h: number }
  note: string
}

export interface Forecast24 {
  available: boolean
  reason?: string
  t: string[]
  top_oil_C: number[]
  hot_spot_C: number[]
  top_oil_lo: number[]
  top_oil_hi: number[]
  hot_spot_lo: number[]
  hot_spot_hi: number[]
  band_low_K: number
  band_high_K: number
  band_basis: string
  peak_hot_spot_C: number
  peak_top_oil_C: number
  method: string
}

export interface Outlook {
  t: string
  rul: RulFan
  trip_risk_30d: { probability: number; days: number; runs: number; limits: { top_oil_C: number; hot_spot_C: number }; median_peak_hot_spot_C: number }
  forecast: Forecast24
}

export interface LossRow { core: number; i2r: number; eddy: number; stray: number; total: number; winding_temp_C: number }

export interface DetailedCompare {
  t_min: number[]
  iec: { top_oil_C: number[]; hot_spot_C: number[] }
  detailed: { top_oil_C: number[]; hot_spot_C: number[] }
  steady_after: { iec: { top_oil_C: number; hot_spot_C: number }; detailed: { top_oil_C: number; hot_spot_C: number } }
  losses: { before: LossRow; after: LossRow }
  viscosity: { oil_at_rated_C: number; ratio_before: number; ratio_after: number; note: string }
  time_constants: {
    iec_nominal_min: number
    iec_63pct_min: number | null
    detailed_63pct_min: number | null
    implied_by_masses: { thermal_capacity_Wh_per_K: number; tau_h: number; note: string } | null
  }
  inputs: { from_pu: number; to_pu: number; ambient_C: number; k_factor: number; use_mass_capacity: boolean }
  assumptions: { note: string }
}

export interface AgeingModels {
  hot_spot_C: number[]
  unit: string
  models: { id: string; label: string; rate: number[] }[]
  note: string
}
