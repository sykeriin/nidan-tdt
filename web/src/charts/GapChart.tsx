// The signature chart: what the sensor says (solid black) against what the physics says (grey), with the gap between them
// hatched. Line style carries the meaning, not hue. Hand-drawn SVG so the 24 h forecast can continue the twin past "now".
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import type { Alert, Run } from '../api/client'
import type { Forecast24 } from '../api/types'
import { alertMs } from '../lib/derive'
import { fmt, indexAt, times, valueAt } from '../lib/series'

const H = 300
const M = { l: 46, r: 14, t: 16, b: 30 }
const DAY = 86400_000

function useWidth() {
  const ref = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(720)
  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([e]) => setW(Math.max(320, Math.floor(e.contentRect.width))))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, w] as const
}

function niceTicks(lo: number, hi: number, n = 5): number[] {
  const raw = (hi - lo) / n
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw
  const out: number[] = []
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Math.round(v * 1000) / 1000)
  return out
}

export type GapWindow = '2d' | '7d' | 'all'

export function GapChart({ run, cursor, bounds, alerts, forecast, window: win }: {
  run: Run
  cursor: number
  bounds: { start: number; end: number }
  alerts: Alert[]
  forecast?: Forecast24
  window: GapWindow
}) {
  const [ref, width] = useWidth()
  const uid = useId().replace(/:/g, '')
  const [hover, setHover] = useState<number | null>(null)
  const measured = run.mode === 'full' ? run.series.OTI_C : undefined
  const twin = run.series.twin_oil_C

  const view = useMemo(() => {
    if (win === 'all') return { x0: bounds.start, x1: bounds.end }
    const span = (win === '2d' ? 2 : 7) * DAY
    const x0 = Math.max(bounds.start, cursor - span)
    return { x0, x1: x0 + span + DAY }
  }, [win, cursor, bounds])

  const innerW = width - M.l - M.r
  const innerH = H - M.t - M.b
  const sx = (ms: number) => M.l + ((ms - view.x0) / (view.x1 - view.x0)) * innerW

  const geo = useMemo(() => {
    const pts = (s: Run['series'][string] | undefined) => {
      if (!s) return []
      const t = times(s)
      const out: [number, number][] = []
      for (let i = 0; i < t.length; i++) {
        if (t[i] < view.x0 - 3600_000) continue
        if (t[i] > Math.min(cursor, view.x1)) break
        if (s.v[i] != null) out.push([t[i], s.v[i] as number])
      }
      return out
    }
    const tp = pts(twin)
    const mp = pts(measured)
    const fx = forecast?.available ? forecast.t.map((x) => Date.parse(x)).filter((x) => x <= view.x1) : []
    const vals = [...tp.map((p) => p[1]), ...mp.map((p) => p[1])]
    if (fx.length && forecast) vals.push(...forecast.top_oil_lo.slice(0, fx.length), ...forecast.top_oil_hi.slice(0, fx.length))
    let lo = vals.length ? Math.min(...vals) : 20
    let hi = vals.length ? Math.max(...vals) : 100
    const pad = Math.max(2, (hi - lo) * 0.08)
    lo -= pad
    hi += pad
    return { tp, mp, fx, lo, hi }
  }, [twin, measured, view, cursor, forecast])

  const sy = (v: number) => M.t + (1 - (v - geo.lo) / (geo.hi - geo.lo)) * innerH
  const line = (p: [number, number][]) => p.map(([t, v], i) => `${i ? 'L' : 'M'}${sx(t).toFixed(1)} ${sy(v).toFixed(1)}`).join(' ')

  // Gap polygon: along the measured trace, back along the twin interpolated at the same instants.
  const gap = useMemo(() => {
    if (!measured || !geo.mp.length || !twin) return ''
    const tt = times(twin)
    const interp = (ms: number) => {
      const i = indexAt(twin, ms)
      if (i < 0) return null
      const a = twin.v[i]
      if (a == null) return null
      const j = i + 1
      if (j >= tt.length || twin.v[j] == null || tt[j] === tt[i]) return a
      return a + ((twin.v[j] as number) - a) * ((ms - tt[i]) / (tt[j] - tt[i]))
    }
    const fwd = geo.mp.map(([t, v]) => [t, v] as [number, number])
    const back = geo.mp.map(([t]) => [t, interp(t)] as [number, number | null]).filter((p): p is [number, number] => p[1] != null).reverse()
    if (!back.length) return ''
    return `${line(fwd)} ${back.map(([t, v]) => `L${sx(t).toFixed(1)} ${sy(v).toFixed(1)}`).join(' ')} Z`
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geo, measured, twin, width])

  const ticksY = niceTicks(geo.lo, geo.hi, 5)
  const spanDays = (view.x1 - view.x0) / DAY
  const stepDays = spanDays > 20 ? Math.ceil(spanDays / 8) : spanDays > 6 ? 1 : 0.5
  const ticksX: number[] = []
  const startDay = Math.ceil((view.x0 + 5.5 * 3600_000) / (stepDays * DAY)) * stepDays * DAY - 5.5 * 3600_000
  for (let t = startDay; t <= view.x1; t += stepDays * DAY) ticksX.push(t)

  const at = hover ?? cursor
  const m = valueAt(measured, at)
  const tw = valueAt(twin, at)
  const g = m != null && tw != null ? m - tw : null
  const visibleAlerts = alerts.filter((a) => a.origin === 'asset' && alertMs(a) >= view.x0 && alertMs(a) <= Math.min(cursor, view.x1))
  const showForecast = !!forecast?.available && geo.fx.length > 1 && win !== 'all'

  return (
    <div ref={ref} className="gapchart">
      <div className="gapchart__legend" aria-live="off">
        <span className="gapchart__key gapchart__key--twin">Twin (physics) <strong>{fmt(tw)} °C</strong></span>
        {measured && <span className="gapchart__key gapchart__key--measured">Measured <strong>{fmt(m)} °C</strong></span>}
        {measured && <span className="gapchart__key gapchart__key--gap">Gap <strong>{g == null ? '—' : `${g >= 0 ? '+' : ''}${g.toFixed(1)} K`}</strong></span>}
        {!measured && <span className="muted">No oil sensor in this dataset: the twin's estimate is shown.</span>}
        {hover != null && <span className="muted">at {new Date(hover + 5.5 * 3600_000).toISOString().slice(5, 16).replace('T', ' ')}</span>}
      </div>
      <svg
        width={width} height={H} viewBox={`0 0 ${width} ${H}`} role="img" aria-label="Measured against twin top-oil temperature, with the gap shaded"
        onPointerMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect()
          const ms = view.x0 + ((e.clientX - r.left - M.l) / innerW) * (view.x1 - view.x0)
          setHover(ms >= view.x0 && ms <= Math.min(cursor, view.x1) ? ms : null)
        }}
        onPointerLeave={() => setHover(null)}
      >
        <defs>
          <pattern id={`hatch-${uid}`} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="5" height="5" fill="rgba(11,11,12,0.06)" />
            <line x1="0" y1="0" x2="0" y2="5" stroke="rgba(11,11,12,0.6)" strokeWidth="1.5" />
          </pattern>
          <clipPath id={`clip-${uid}`}><rect x={M.l} y={M.t - 4} width={innerW} height={innerH + 8} /></clipPath>
        </defs>

        {ticksY.map((v) => (
          <g key={v}>
            <line x1={M.l} x2={width - M.r} y1={sy(v)} y2={sy(v)} stroke="rgba(11,11,12,0.07)" />
            <text x={M.l - 8} y={sy(v) + 4} textAnchor="end" fontSize={11} fill="var(--muted)">{v}</text>
          </g>
        ))}
        {ticksX.map((t) => (
          <text key={t} x={sx(t)} y={H - 10} textAnchor="middle" fontSize={11} fill="var(--muted)">
            {new Date(t + 5.5 * 3600_000).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' })}
          </text>
        ))}
        <text x={12} y={M.t + 4} fontSize={11} fill="var(--muted)" transform={`rotate(-90 12 ${M.t + 4})`} textAnchor="end">Top oil °C</text>

        <g clipPath={`url(#clip-${uid})`}>
          {showForecast && forecast && (
            <>
              <rect x={sx(cursor)} y={M.t - 4} width={Math.max(0, width - M.r - sx(cursor))} height={innerH + 8} fill="rgba(11,11,12,0.03)" />
              <path
                d={`${geo.fx.map((t, i) => `${i ? 'L' : 'M'}${sx(t).toFixed(1)} ${sy(forecast.top_oil_hi[i]).toFixed(1)}`).join(' ')} ${[...geo.fx].reverse().map((t, i) => `L${sx(t).toFixed(1)} ${sy(forecast.top_oil_lo[geo.fx.length - 1 - i]).toFixed(1)}`).join(' ')} Z`}
                fill="rgba(11,11,12,0.07)"
              />
              <path d={geo.fx.map((t, i) => `${i ? 'L' : 'M'}${sx(t).toFixed(1)} ${sy(forecast.top_oil_C[i]).toFixed(1)}`).join(' ')} fill="none" stroke="var(--twin)" strokeWidth={1.6} strokeDasharray="5 4" />
              <text x={sx(cursor) + 8} y={M.t + 10} fontSize={11} fill="var(--text-2)">24 h forecast</text>
            </>
          )}
          {gap && <path d={gap} fill={`url(#hatch-${uid})`} />}
          {geo.tp.length > 1 && <path d={line(geo.tp)} fill="none" stroke="var(--twin)" strokeWidth={2} strokeLinejoin="round" />}
          {geo.mp.length > 1 && <path d={line(geo.mp)} fill="none" stroke="var(--measured)" strokeWidth={1.6} strokeLinejoin="round" />}
          {visibleAlerts.slice(-80).map((a) => (
            <line key={a.id} x1={sx(alertMs(a))} x2={sx(alertMs(a))} y1={M.t + innerH - 12} y2={M.t + innerH}
              stroke={a.severity === 'critical' ? 'var(--crit)' : 'var(--warn)'} strokeWidth={2} />
          ))}
          {hover != null && <line x1={sx(hover)} x2={sx(hover)} y1={M.t} y2={M.t + innerH} stroke="var(--text-2)" strokeOpacity={0.4} strokeDasharray="2 3" />}
          <line x1={sx(cursor)} x2={sx(cursor)} y1={M.t} y2={M.t + innerH} stroke="var(--text)" strokeOpacity={0.55} />
        </g>
        <text x={Math.min(width - M.r - 4, sx(cursor) + 6)} y={H - 10} fontSize={11} fill="var(--text-2)" textAnchor={sx(cursor) > width - 60 ? 'end' : 'start'}>now</text>
      </svg>
    </div>
  )
}
