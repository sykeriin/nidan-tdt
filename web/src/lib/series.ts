import type { Series } from '../api/client'

/** Epoch-ms array for a series, cached per object (series are immutable once fetched). */
const cache = new WeakMap<Series, number[]>()
export function times(s: Series): number[] {
  let t = cache.get(s)
  if (!t) {
    t = s.t.map((x) => Date.parse(x))
    cache.set(s, t)
  }
  return t
}

/** Index of the last sample at or before `ms`, or -1. */
export function indexAt(s: Series | undefined, ms: number): number {
  if (!s) return -1
  const t = times(s)
  let lo = 0
  let hi = t.length - 1
  let ans = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (t[mid] <= ms) {
      ans = mid
      lo = mid + 1
    } else hi = mid - 1
  }
  return ans
}

/** Latest value at or before `ms`. A sample older than `maxAgeMs` counts as missing, so gaps are not bridged. */
export function valueAt(s: Series | undefined, ms: number, maxAgeMs = 6 * 3600_000): number | null {
  const i = indexAt(s, ms)
  if (i < 0) return null
  if (ms - times(s!)[i] > maxAgeMs) return null
  return s!.v[i]
}

/** Samples within [from, to] as parallel arrays. */
export function slice(s: Series | undefined, from: number, to: number): { t: string[]; v: (number | null)[] } {
  if (!s) return { t: [], v: [] }
  const t = times(s)
  const out = { t: [] as string[], v: [] as (number | null)[] }
  for (let i = 0; i < t.length; i++) {
    if (t[i] > to) break
    if (t[i] >= from) {
      out.t.push(s.t[i])
      out.v.push(s.v[i])
    }
  }
  return out
}

export const bandOf = (score: number): 'green' | 'yellow' | 'red' =>
  score >= 80 ? 'green' : score >= 60 ? 'yellow' : 'red'

export const fmt = (v: number | null | undefined, digits = 1): string =>
  v == null || Number.isNaN(v) ? '—' : v.toFixed(digits)

export const fmtTime = (iso: string | number | null | undefined): string => {
  if (iso == null) return '—'
  const d = new Date(iso)
  return d.toLocaleString('en-GB', {
    timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
    hour12: false,
  })
}
