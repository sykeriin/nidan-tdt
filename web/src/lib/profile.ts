import type { ProfileBody } from '../api/client'

/** Profile fields typed as text in the form; everything else is sent as a number. */
export const TEXT_FIELDS = new Set(['name', 'site', 'cooling', 'vector_group', 'insulation', 'breather'])

export type Typed = Record<string, string>

export function toBody(typed: Typed, tags: Record<string, string>): ProfileBody {
  const values: Record<string, unknown> = {}
  const keep: Record<string, string> = {}
  for (const [k, raw] of Object.entries(typed)) {
    const v = raw.trim()
    if (v === '') continue
    values[k] = TEXT_FIELDS.has(k) ? v : Number(v)
    if (tags[k]) keep[k] = tags[k]
  }
  return { values, tags: keep }
}

export const isReady = (typed: Typed) => {
  const kva = Number(typed.rating_kVA)
  const amps = Number(typed.i_rated_A)
  return (Number.isFinite(kva) && kva > 0) || (Number.isFinite(amps) && amps > 0)
}

export function fromPreset(values: Record<string, unknown>): Typed {
  return Object.fromEntries(Object.entries(values).map(([k, v]) => [k, String(v)]))
}
