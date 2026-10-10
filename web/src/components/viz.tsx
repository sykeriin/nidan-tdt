import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import type { Advice, Diagnosis, RulFan as RulFanData } from '../api/types'
import type { Band } from '../lib/derive'

/** Eases a displayed number towards its target, so the dial and gap meter move instead of jumping. */
export function useTween(target: number | null, ms = 450): number | null {
  const [shown, setShown] = useState<number | null>(target)
  const from = useRef<number | null>(target)
  const raf = useRef(0)
  useEffect(() => {
    if (target == null || from.current == null || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      from.current = target
      setShown(target)
      return
    }
    const start = from.current
    const t0 = performance.now()
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / ms)
      const e = 1 - (1 - k) ** 3
      const v = start + (target - start) * e
      from.current = v
      setShown(v)
      if (k < 1) raf.current = requestAnimationFrame(step)
    }
    raf.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf.current)
  }, [target, ms])
  return shown
}

const BAND_VAR: Record<Band, string> = { green: 'var(--ok)', yellow: 'var(--warn)', red: 'var(--crit)' }

/** Health Index dial: a 240° arc with the band edges (60, 80) marked. */
export function HealthDial({ score, band, capped }: { score: number | null; band: Band | null; capped: boolean }) {
  const id = useId().replace(/:/g, '')
  const shown = useTween(score)
  const cx = 100, cy = 100, r = 78
  const a0 = 150, sweep = 240                                   // degrees: from lower-left, clockwise
  const pt = (deg: number, rad = r) => [cx + rad * Math.cos((deg * Math.PI) / 180), cy + rad * Math.sin((deg * Math.PI) / 180)]
  const arc = (from: number, to: number, rad = r) => {
    const [x1, y1] = pt(a0 + (from / 100) * sweep, rad)
    const [x2, y2] = pt(a0 + (to / 100) * sweep, rad)
    return `M${x1.toFixed(2)} ${y1.toFixed(2)} A${rad} ${rad} 0 ${(to - from) / 100 * sweep > 180 ? 1 : 0} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`
  }
  const v = shown == null ? 0 : Math.max(0, Math.min(100, shown))
  const colour = band ? BAND_VAR[band] : 'var(--stale)'
  return (
    <div className="dial" role="img" aria-label={`Health index ${score == null ? 'unavailable' : Math.round(score)} out of 100`}>
      <svg viewBox="0 0 200 150">
        <defs>
          <filter id={`g-${id}`} x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="3.5" /></filter>
        </defs>
        <path d={arc(0, 100)} fill="none" stroke="rgba(11,11,12,0.08)" strokeWidth={13} strokeLinecap="round" />
        {[60, 80].map((t) => {
          const [x1, y1] = pt(a0 + (t / 100) * sweep, r - 11)
          const [x2, y2] = pt(a0 + (t / 100) * sweep, r + 11)
          return <line key={t} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--panel)" strokeWidth={3} />
        })}
        {v > 0.5 && <path d={arc(0, v)} fill="none" stroke={colour} strokeWidth={13} strokeLinecap="round" />}
      </svg>
      <div className="dial__value" style={{ color: colour }}>{score == null ? '—' : Math.round(shown ?? score)}</div>
      {capped && <p className="dial__cap">Capped at 40 by a critical alarm</p>}
    </div>
  )
}

export function Sparkline({ values, color = 'var(--text-2)', band }: { values: (number | null)[]; color?: string; band?: [number, number] }) {
  const ok = values.filter((v): v is number => v != null)
  if (ok.length < 2) return <svg className="spark" viewBox="0 0 100 34" aria-hidden />
  const lo = Math.min(...ok), hi = Math.max(...ok), span = hi - lo || 1
  const pts = values.map((v, i) => (v == null ? null : [(i / (values.length - 1)) * 100, 30 - ((v - lo) / span) * 26] as [number, number]))
  let d = ''
  let pen = false
  for (const p of pts) {
    if (!p) { pen = false; continue }
    d += `${pen ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)} `
    pen = true
  }
  const last = [...pts].reverse().find((p) => p)
  return (
    <svg className="spark" viewBox="0 0 100 34" preserveAspectRatio="none" aria-hidden>
      {band && <rect x={0} width={100} y={30 - ((band[1] - lo) / span) * 26} height={Math.max(0, ((band[1] - band[0]) / span) * 26)} fill="rgba(11,11,12,0.04)" />}
      <path d={d} fill="none" stroke={color} strokeWidth={1.4} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      {last && <circle cx={last[0]} cy={last[1]} r={2.2} fill={color} vectorEffect="non-scaling-stroke" />}
    </svg>
  )
}

export function Instrument({ name, value, unit, sub, tone = 'default', state = 'ok', spark, sparkColor }: {
  name: string; value: string; unit?: string; sub?: ReactNode; tone?: 'default' | 'twin' | 'measured' | 'gap'
  state?: 'ok' | 'watch' | 'critical'; spark?: (number | null)[]; sparkColor?: string
}) {
  return (
    <div className={`inst inst--${tone}`} data-state={state}>
      <span className="inst__name">{name}</span>
      <span className="inst__value">{value}{unit && <span className="inst__unit">{unit}</span>}</span>
      <span className="inst__sub">{sub}</span>
      {spark && <Sparkline values={spark} color={sparkColor ?? (tone === 'measured' ? 'var(--measured)' : tone === 'gap' ? 'var(--gap)' : 'var(--twin)')} />}
    </div>
  )
}

export function DiagnosisBars({ diagnosis }: { diagnosis: Diagnosis[] }) {
  const shown = diagnosis.filter((d) => d.observable && d.evidence >= 0.15).slice(0, 4)
  const blind = diagnosis.filter((d) => !d.observable)
  if (!diagnosis.length) return <p className="muted">No diagnosis for this dataset.</p>
  return (
    <>
      {shown.length === 0 ? (
        <p className="muted">Nothing stands out: no fault class has meaningful evidence right now.</p>
      ) : (
        <ul className="diag">
          {shown.map((d) => (
            <li key={d.fault}>
              <span className="diag__name">{d.label}</span>
              <span className="diag__share">{Math.round(d.share * 100)}%</span>
              <span className="diag__bar"><span style={{ width: `${Math.max(3, d.share * 100)}%` }} /></span>
              <span className="diag__why">{d.why}</span>
            </li>
          ))}
        </ul>
      )}
      {blind.length > 0 && (
        <p className="muted" style={{ marginTop: 10 }}>Not observable with these inputs: {blind.map((d) => d.label.toLowerCase()).join(', ')}.</p>
      )}
    </>
  )
}

const URGENCY: Record<string, string> = { immediate: 'Immediately', '24h': 'Within 24 h', '7d': 'Within 7 days', next_scheduled: 'Next scheduled' }

export function WorkOrder({ advice }: { advice: Advice | null }) {
  if (!advice) return <p className="muted">No maintenance guidance for this dataset.</p>
  return (
    <div className="work">
      <div className="work__head">
        <span className="work__priority" data-p={advice.priority}>{advice.priority}</span>
        <span className="muted">{advice.schedule}</span>
      </div>
      {advice.actions.length ? (
        <ol>
          {advice.actions.slice(0, 3).map((a, i) => (
            <li key={`${a.action}-${i}`}>
              <strong>{a.action}</strong>
              <span>{a.test ? `Test: ${a.test}. ` : ''}{URGENCY[a.urgency] ?? a.urgency}{a.standard_ref ? `. Ref: ${a.standard_ref}` : ''}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="muted">No action needed beyond routine inspection.</p>
      )}
      <p className="muted">{advice.note}</p>
    </div>
  )
}

const YEARS_CAP = 40
const yearsText = (y: number) => (y >= YEARS_CAP ? `more than ${YEARS_CAP}` : y.toFixed(y < 10 ? 1 : 0))

/** Fan chart of insulation life consumed over the next 40 years (Monte Carlo P10 / P50 / P90). */
export function RulFan({ rul }: { rul: RulFanData }) {
  const id = useId().replace(/:/g, '')
  const W = 360, H = 190, m = { l: 36, r: 10, t: 10, b: 24 }
  const x = (y: number) => m.l + (y / YEARS_CAP) * (W - m.l - m.r)
  const yy = (p: number) => m.t + (1 - p / 100) * (H - m.t - m.b)
  const { years, p10, p50, p90 } = rul.fan
  const path = (v: number[]) => v.map((p, i) => `${i ? 'L' : 'M'}${x(years[i]).toFixed(1)} ${yy(p).toFixed(1)}`).join(' ')
  const band = `${path(p90)} ${[...years].reverse().map((yr, i) => `L${x(yr).toFixed(1)} ${yy(p10[years.length - 1 - i]).toFixed(1)}`).join(' ')} Z`
  return (
    <>
      <svg className="fan" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Insulation life consumed over ${YEARS_CAP} years; median remaining life ${yearsText(rul.years_p50)} years`}>
        <defs>
          <linearGradient id={`f-${id}`} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#0b0b0c" stopOpacity="0.2" /><stop offset="1" stopColor="#0b0b0c" stopOpacity="0.04" /></linearGradient>
        </defs>
        {[0, 50, 100].map((p) => (
          <g key={p}>
            <line x1={m.l} x2={W - m.r} y1={yy(p)} y2={yy(p)} stroke="rgba(11,11,12,0.08)" />
            <text x={m.l - 6} y={yy(p) + 4} textAnchor="end">{p}%</text>
          </g>
        ))}
        {[0, 10, 20, 30, 40].map((yr) => <text key={yr} x={x(yr)} y={H - 6} textAnchor="middle">{yr === 0 ? 'now' : `${yr} y`}</text>)}
        <line x1={m.l} x2={W - m.r} y1={yy(100)} y2={yy(100)} stroke="var(--crit)" strokeDasharray="4 4" strokeOpacity={0.8} />
        <text x={W - m.r} y={yy(100) - 5} textAnchor="end" fill="var(--crit-text)">reference life used up</text>
        <path d={band} fill={`url(#f-${id})`} />
        <path d={path(p50)} fill="none" stroke="var(--text)" strokeWidth={2} />
      </svg>
      <dl className="kv" style={{ marginTop: 6 }}>
        <dt>Median remaining life</dt><dd>{yearsText(rul.years_p50)} years</dd>
        <dt>1 chance in 10 of less than</dt><dd>{yearsText(rul.years_p10)} years</dd>
        <dt>1 chance in 10 of more than</dt><dd>{yearsText(rul.years_p90)} years</dd>
      </dl>
    </>
  )
}
