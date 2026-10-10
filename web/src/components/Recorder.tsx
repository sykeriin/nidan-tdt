// The flight-recorder dock: transport, a scrubbable timeline painted with the Health Index and every alert,
// and the clock. Replay is client-side, so scrubbing is instant.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { SPEEDS, useSession } from '../context/Session'
import { alertMs } from '../lib/derive'
import { bandOf, fmtTime, valueAt } from '../lib/series'

const BINS = 220
const BAND_COLOUR = { green: 'var(--ok)', yellow: 'var(--warn)', red: 'var(--crit)' } as const

function useWidth() {
  const ref = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(600)
  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([e]) => setW(Math.max(200, Math.floor(e.contentRect.width))))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, w] as const
}

function Timeline() {
  const s = useSession()
  const [ref, width] = useWidth()
  const dragging = useRef(false)
  const [hover, setHover] = useState<number | null>(null)
  const b = s.bounds
  const span = b ? b.end - b.start : 1
  const height = 54

  const ribbon = useMemo(() => {
    if (!s.run || !b) return []
    const score = s.run.health_series.score
    return Array.from({ length: BINS }, (_, i) => {
      const v = valueAt(score, b.start + ((i + 0.5) / BINS) * span, 48 * 3600_000)
      return v == null ? null : bandOf(v)
    })
  }, [s.run, b, span])

  const ticks = useMemo(() => {
    const bins = Array.from({ length: BINS }, () => ({ crit: 0, warn: 0, sensor: 0 }))
    if (!b) return bins
    for (const a of s.alerts) {
      const i = Math.min(BINS - 1, Math.max(0, Math.floor(((alertMs(a) - b.start) / span) * BINS)))
      if (a.origin === 'sensor') bins[i].sensor++
      else if (a.severity === 'critical') bins[i].crit++
      else bins[i].warn++
    }
    return bins
  }, [s.alerts, b, span])

  const xToMs = useCallback((clientX: number) => {
    const r = ref.current!.getBoundingClientRect()
    return b!.start + Math.min(1, Math.max(0, (clientX - r.left) / r.width)) * span
  }, [ref, b, span])

  if (!b || s.cursor == null) return <p className="muted">No time axis in this dataset.</p>
  const px = (ms: number) => ((ms - b.start) / span) * width
  const days = Math.max(1, Math.round(span / 86400_000))
  const dayStep = days > 40 ? Math.ceil(days / 8) : days > 14 ? 5 : 2
  const labels: { x: number; text: string }[] = []
  for (let d = 0; d <= days; d += dayStep) {
    const ms = b.start + d * 86400_000
    if (ms <= b.end) labels.push({ x: px(ms), text: new Date(ms + 5.5 * 3600_000).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' }) })
  }
  const bw = width / BINS

  return (
    <div
      className="scrub" ref={ref} role="slider" aria-label="Replay position" aria-valuemin={b.start} aria-valuemax={b.end} aria-valuenow={s.cursor}
      tabIndex={0}
      onPointerDown={(e) => { dragging.current = true; (e.target as Element).setPointerCapture?.(e.pointerId); s.setCursor(xToMs(e.clientX)) }}
      onPointerMove={(e) => { setHover(xToMs(e.clientX)); if (dragging.current) s.setCursor(xToMs(e.clientX)) }}
      onPointerUp={() => { dragging.current = false }}
      onPointerLeave={() => setHover(null)}
    >
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" width={width} height={height}>
        {/* Health Index ribbon */}
        {ribbon.map((band, i) => (
          <rect key={i} x={i * bw} y={14} width={bw + 0.5} height={11} rx={1.5} fill={band ? BAND_COLOUR[band] : 'var(--border)'} opacity={band ? 0.78 : 0.5} />
        ))}
        {/* alerts */}
        {ticks.map((t, i) => {
          const h = t.crit ? 14 : t.warn ? 10 : t.sensor ? 6 : 0
          if (!h) return null
          const fill = t.crit ? 'var(--crit)' : t.warn ? 'var(--warn)' : 'var(--sensor)'
          return <rect key={`a${i}`} x={i * bw} y={28} width={Math.max(1.6, bw - 0.6)} height={h} rx={1} fill={fill} />
        })}
        {labels.map((l) => (
          <text key={l.x} x={l.x} y={52} fontSize={10} fill="var(--muted)" textAnchor="middle">{l.text}</text>
        ))}
        {hover != null && <line x1={px(hover)} x2={px(hover)} y1={6} y2={46} stroke="var(--text-2)" strokeOpacity={0.35} strokeDasharray="2 3" />}
        {/* playhead */}
        <line x1={px(s.cursor)} x2={px(s.cursor)} y1={2} y2={46} stroke="var(--text)" strokeWidth={2} />
        <circle cx={px(s.cursor)} cy={4} r={5} fill="var(--text)" />
      </svg>
      {hover != null && (
        <span className="scrub__tip" style={{ left: Math.min(width - 90, Math.max(0, px(hover) - 45)) }}>{fmtTime(hover)}</span>
      )}
    </div>
  )
}

export function Recorder() {
  const s = useSession()
  if (!s.run || s.run.mode === 'snapshot' || s.run.mode === 'data_only') return null
  return (
    <div className="dock">
      <div className="dock__inner">
        <div className="dock__transport">
          <button className="dock__step" type="button" onClick={s.prevAlert} aria-label="Previous alert" title="Previous alert (P)">⏮</button>
          <button className="dock__step" type="button" onClick={() => s.stepBy(-3600_000)} aria-label="Back one hour" title="Back 1 h (←)">◀</button>
          <button className="dock__play" type="button" onClick={s.togglePlay} aria-label={s.playing ? 'Pause replay' : 'Play replay'} title="Play / pause (space)">
            {s.playing ? '❚❚' : '▶'}
          </button>
          <button className="dock__step" type="button" onClick={() => s.stepBy(3600_000)} aria-label="Forward one hour" title="Forward 1 h (→)">▶</button>
          <button className="dock__step" type="button" onClick={s.nextAlert} aria-label="Next alert" title="Next alert (N)">⏭</button>
        </div>
        <Timeline />
        <div className="dock__clock">
          <div className="dock__time">{s.cursor != null ? fmtTime(s.cursor) : '—'}</div>
          <div className="dock__sub">IST · {s.simulated ? 'simulated data' : 'recorded data'}</div>
          <div className="dock__speed" role="group" aria-label="Replay speed">
            {SPEEDS.map((p) => (
              <button key={p.value} type="button" aria-pressed={s.speed === p.value} title={p.hint} onClick={() => s.setSpeed(p.value)}>{p.label}</button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
