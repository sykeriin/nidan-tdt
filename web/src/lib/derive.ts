import type { Alert, Run } from '../api/client'
import { bandOf, valueAt } from './series'

export type Band = 'green' | 'yellow' | 'red'

export interface HealthNow {
  score: number | null
  band: Band | null
  capped: boolean
  components: Record<string, number>
  weights: Record<string, number>
}

export interface Now {
  ms: number
  /** Latest measured / twin value of any trend column at the cursor, or null. */
  at: (col: string) => number | null
  health: HealthNow
  /** Alerts raised in the 24 h up to the cursor (the same window the backend's state endpoint uses). */
  active: Alert[]
  /** Every alert raised up to the cursor. */
  raised: Alert[]
}

export const ALERT_WINDOW_MS = 24 * 3600_000
export const SUB_SCORES = ['thermal', 'ageing', 'loading', 'electrical', 'integrity', 'fault_stress'] as const
const HEALTH_MAX_AGE = 7 * 24 * 3600_000

export function alertMs(a: Alert): number {
  return Date.parse(a.timestamp)
}

export function sortedAlerts(run: Run): Alert[] {
  return [...run.analysis.alerts].sort((a, b) => alertMs(a) - alertMs(b))
}

export function nowAt(run: Run, alerts: Alert[], ms: number): Now {
  const at = (col: string) => valueAt(run.series[col], ms)
  const hs = run.health_series
  const score = valueAt(hs.score, ms, HEALTH_MAX_AGE)
  const components: Record<string, number> = {}
  for (const k of SUB_SCORES) {
    const v = valueAt(hs[k], ms, HEALTH_MAX_AGE)
    if (v != null) components[k] = v
  }
  const raised = alerts.filter((a) => alertMs(a) <= ms)
  const active = raised.filter((a) => ms - alertMs(a) <= ALERT_WINDOW_MS)
  return {
    ms,
    at,
    health: {
      score,
      band: score == null ? null : bandOf(score),
      capped: (valueAt(hs.capped, ms, HEALTH_MAX_AGE) ?? 0) > 0,
      components,
      weights: run.analysis.health.weights,
    },
    active,
    raised,
  }
}
