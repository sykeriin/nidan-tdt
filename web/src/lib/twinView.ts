// Builds the TwinView object the 3D component draws (UI_DESIGN section 6.6). Ported from app/twin_view.py on the
// powernext-pt2 branch. It only places alerts on parts and formats readings: detection and severity come from
// the analytics unchanged.
import type { Alert, Recommendation, Run } from '../api/client'
import type { Now } from './derive'
import { slice, valueAt } from './series'

export const PART_IDS = ['windings', 'tank', 'radiators', 'conservator', 'bushings', 'core'] as const
export type PartId = (typeof PART_IDS)[number]
export type Status = 'green' | 'yellow' | 'red' | 'grey'

export interface Reading {
  label: string
  value: number
  unit: string
  twin: number | null
}
export interface PartView {
  status: Status
  available: boolean
  estimated: boolean
  readings: Reading[]
  alert_ids: string[]
  sensor_alert_ids: string[]
}
export interface ViewAlert {
  id: string
  timestamp: string
  part: PartId | 'general'
  module: string
  type: string
  severity: string
  origin: string
  detector: string
  value: number | null
  threshold: number | null
  explanation: string
  lead_time_h: number | null
  simulated: boolean
  recommendation: { action: string; test: string | null; urgency: string; standard_ref: string | null } | null
}
export interface TwinView {
  timestamp: string
  simulated: boolean
  mode: string
  source_label: string
  health: { score: number | null; band: string | null; capped: boolean }
  parts: Record<PartId, PartView>
  alerts: ViewAlert[]
  history: Partial<Record<PartId, { t: string[]; measured: (number | null)[]; twin: (number | null)[] }>>
  /** Temperature per part for the heat-map view: measured where there is a sensor, otherwise the twin's estimate. */
  heat: Partial<Record<PartId, number>>
}

const ALERT_TO_PART: Record<string, PartId> = {
  overload: 'windings', loading: 'windings', loading_high: 'windings', overcurrent: 'windings',
  hot_spot: 'windings', hot_spot_high: 'windings', unbalance: 'windings', current_unbalance: 'windings',
  neutral: 'windings', through_fault: 'windings', through_fault_stress: 'windings',
  insulation: 'windings', ageing: 'windings', ageing_rate_high: 'windings',
  top_oil_high: 'tank', top_oil: 'tank', jump_oti: 'tank', stuck_oti: 'tank', implausible_sensor: 'tank',
  fidelity: 'tank', model_drift: 'tank',
  residual_drift: 'radiators',
  oil_leak: 'conservator', oil_theft: 'conservator', oil_level_low: 'conservator', oil_low: 'conservator',
  drift_sensor: 'conservator', moisture: 'conservator', breathing: 'conservator',
  voltage_high: 'bushings', voltage_low: 'bushings', voltage_unbalance: 'bushings',
}
const MODULE_TO_PART: Record<string, PartId> = {
  overloading: 'windings', short_circuit: 'windings', insulation: 'windings', oil: 'conservator',
  moisture: 'conservator',
}
// Sensor alerts name their channel in the text; the part that owns the channel gets the badge.
// [case-sensitive acronyms, case-insensitive words, part]. Acronyms must not match prose: "in" or "ir" in a
// sentence is not the IN / IR channel.
const CHANNELS: [RegExp, RegExp, PartId][] = [
  [/\b(OTI|ATI)(?![A-Za-z])/, /top[- ]oil/i, 'tank'],
  [/\b(WTI|IR|IY|IB|IN)(?![A-Za-z])/, /current|hot[- ]spot/i, 'windings'],
  [/\b(OLI|RH)(?![A-Za-z])/, /oil level|humidity/i, 'conservator'],
  [/\b(VR|VY|VB|PF)(?![A-Za-z])/, /voltage|frequency/i, 'bushings'],
]

export function partFor(a: Alert): PartId | 'general' {
  const direct = ALERT_TO_PART[a.type]
  if (direct) return direct
  if (MODULE_TO_PART[a.module]) return MODULE_TO_PART[a.module]
  const text = `${a.type.replace(/_/g, ' ')} ${a.explanation}`
  const hit = CHANNELS.find(([acr, words]) => acr.test(text) || words.test(text))
  return hit?.[2] ?? (a.module === 'electrical' ? 'windings' : 'general')
}

const SEVERITY_STATUS: Record<string, Status> = { critical: 'red', warning: 'yellow', info: 'green' }
const STATUS_ORDER: Record<Status, number> = { grey: -1, green: 0, yellow: 1, red: 2 }

const round = (v: number | null | undefined, d = 1): number | null =>
  v == null || Number.isNaN(v) ? null : Math.round(v * 10 ** d) / 10 ** d

function reading(label: string, v: number | null, unit: string, twin: number | null = null, d = 1): Reading | null {
  const value = round(v, d)
  return value == null ? null : { label, value, unit, twin: round(twin, d) }
}

const compact = (xs: (Reading | null)[]): Reading[] => xs.filter((x): x is Reading => x !== null)

export function buildTwinView(run: Run, now: Now, label: string, simulated: boolean): TwinView {
  const r = now.at
  const mode = run.mode
  const measured = mode === 'full'
  const recs = new Map<string, Recommendation>(run.analysis.recommendations.map((x) => [x.id, x]))

  const volts = ['VR', 'VY', 'VB'].map(r)
  let vUnbalance: number | null = null
  if (volts.every((v) => v != null)) {
    const vs = volts as number[]
    const mean = vs.reduce((a, b) => a + b, 0) / 3
    vUnbalance = mean ? (Math.max(...vs.map((v) => Math.abs(v - mean))) / mean) * 100 : null
  }

  const readings: Record<PartId, Reading[]> = {
    windings: compact([
      reading('Loading', r('loading_pct'), '%'),
      reading('Current R', r('IR'), 'A', null, 0),
      reading('Current Y', r('IY'), 'A', null, 0),
      reading('Current B', r('IB'), 'A', null, 0),
      measured && r('WTI_C') != null
        ? reading('Hot-spot (WTI)', r('WTI_C'), '°C', r('twin_hs_C'))
        : reading('Hot-spot (estimated)', r('twin_hs_C'), '°C'),
      reading('Ageing rate', r('aging_rate'), 'x', null, 2),
    ]),
    tank: compact([
      measured ? reading('Top oil', r('OTI_C'), '°C', r('twin_oil_C')) : reading('Top oil (estimated)', r('twin_oil_C'), '°C'),
      reading('Ambient', r('amb_C'), '°C'),
    ]),
    radiators: measured
      ? compact([
          reading('Residual', r('residual_oil_C'), '°C'),
          reading('Fidelity RMSE', r('fidelity_rmse_C'), '°C'),
          reading('Top oil', r('OTI_C'), '°C', r('twin_oil_C')),
        ])
      : [],
    conservator: compact([reading('Oil level', r('OLI_pct'), '%'), reading('Humidity', r('RH_pct'), '%', null, 0)]),
    bushings: compact([
      reading('Voltage R', r('VR'), 'V'),
      reading('Voltage Y', r('VY'), 'V'),
      reading('Voltage B', r('VB'), 'V'),
      reading('Voltage unbalance', vUnbalance, '%', null, 2),
      reading('Power factor', r('PF'), '', null, 2),
      reading('Frequency', r('freq_Hz'), 'Hz', null, 2),
    ]),
    core: [],
  }

  const has = (...cols: string[]) => cols.some((c) => r(c) != null)
  const available: Record<PartId, boolean> = {
    windings: has('I_mean', 'IR', 'loading_pct'),
    tank: (mode === 'full' && has('OTI_C')) || (mode === 'meter_only' && has('twin_oil_C')),
    radiators: mode === 'full' && has('OTI_C'),
    conservator: has('OLI_pct'),
    bushings: has('VR', 'VY', 'VB'),
    core: false,
  }

  const parts = Object.fromEntries(
    PART_IDS.map((id) => [
      id,
      {
        status: available[id] ? 'green' : 'grey',
        available: available[id],
        estimated: mode === 'meter_only' && (id === 'tank' || id === 'radiators'),
        readings: available[id] ? readings[id] : [],
        alert_ids: [],
        sensor_alert_ids: [],
      } as PartView,
    ]),
  ) as Record<PartId, PartView>

  const alerts: ViewAlert[] = []
  for (const a of now.active) {
    const part = partFor(a)
    const rec = a.recommendation_id ? recs.get(a.recommendation_id) : undefined
    alerts.push({
      id: a.id, timestamp: a.timestamp, part, module: a.module, type: a.type, severity: a.severity,
      origin: a.origin, detector: a.detector, value: round(a.value, 2), threshold: round(a.threshold, 2),
      explanation: a.explanation, lead_time_h: round(a.lead_time_h), simulated: a.simulated,
      recommendation: rec ? { action: rec.action, test: rec.test, urgency: rec.urgency, standard_ref: rec.standard_ref } : null,
    })
    if (part === 'general' || part === 'core') continue
    if (a.origin === 'sensor') {
      // Check the device, not the transformer: a badge, never a red part.
      parts[part].sensor_alert_ids.push(a.id)
      continue
    }
    parts[part].alert_ids.push(a.id)
    const next = SEVERITY_STATUS[a.severity] ?? 'green'
    const cur = parts[part].status
    parts[part].status = STATUS_ORDER[next] > STATUS_ORDER[cur] ? next : cur === 'grey' ? 'green' : cur
  }

  // Last 48 h of replay for parts with a measured-vs-twin pair.
  const from = now.ms - 48 * 3600_000
  const pair = (m: string, t: string) => {
    const ms = slice(run.series[m], from, now.ms)
    if (!ms.t.length || ms.v.every((v) => v == null)) return undefined
    return { t: ms.t, measured: ms.v, twin: ms.t.map((x) => valueAt(run.series[t], Date.parse(x), 3600_000)) }
  }
  const history: TwinView['history'] = {}
  if (mode === 'full') {
    const oil = pair('OTI_C', 'twin_oil_C')
    if (oil) {
      history.tank = oil
      history.radiators = oil
    }
    const hs = pair('WTI_C', 'twin_hs_C')
    if (hs) history.windings = hs
  }

  const oilNow = measured && r('OTI_C') != null ? r('OTI_C') : r('twin_oil_C')
  const hsNow = measured && r('WTI_C') != null ? r('WTI_C') : r('twin_hs_C')
  const heat: TwinView['heat'] = {}
  if (hsNow != null) heat.windings = hsNow
  if (oilNow != null) {
    heat.tank = oilNow
    heat.radiators = oilNow
  }
  // The conservator and bushings have no temperature estimate, so they stay grey rather than being coloured by guesswork.

  return {
    timestamp: new Date(now.ms).toISOString(),
    simulated,
    mode,
    source_label: label,
    health: { score: round(now.health.score), band: now.health.band, capped: now.health.capped },
    parts,
    alerts: alerts.sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp)).slice(0, 60),
    history,
    heat,
  }
}
