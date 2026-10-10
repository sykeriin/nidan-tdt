import Plotly from 'plotly.js-basic-dist-min'
import createPlotlyComponent from 'react-plotly.js/factory'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { Alert, Series } from '../api/client'
import { alertMs } from '../lib/derive'
import { times } from '../lib/series'

const Plot = createPlotlyComponent(Plotly)

export interface TraceSpec {
  name: string
  series?: Series
  color: string
  dash?: 'solid' | 'dash' | 'dot'
  width?: number
  /** Fill down to the previous trace (used for the measured-vs-twin gap). */
  fillPrev?: boolean
}

interface Props {
  traces: TraceSpec[]
  /** Full data range in epoch ms: the x axis stays fixed while a replay fills it in. */
  range: [number, number] | null
  cursor: number | null
  height?: number
  yTitle?: string
  hlines?: { y: number; label: string }[]
  alerts?: Alert[]
  /** Draw data only up to the cursor (replay). */
  clip?: boolean
}

/** Real throttle: update at most every `ms` while the value keeps changing, and always settle on the last value. */
function useThrottled<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  const lastRun = useRef(0)
  useEffect(() => {
    const wait = lastRun.current + ms - Date.now()
    if (wait <= 0) {
      lastRun.current = Date.now()
      setV(value)
      return
    }
    const id = window.setTimeout(() => {
      lastRun.current = Date.now()
      setV(value)
    }, wait)
    return () => window.clearTimeout(id)
  }, [value, ms])
  return v
}

/** Plotly draws the "+05:30" data timestamps as IST wall-clock time and ignores the offset, so every
 *  other x value (cursor, alert markers, axis range) must be given as IST wall-clock text too. */
const IST_OFFSET_MS = 5.5 * 3600_000
const ist = (ms: number) => new Date(ms + IST_OFFSET_MS).toISOString().slice(0, 19)

const css = (name: string, fallback: string) => {
  if (typeof document === 'undefined') return fallback
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

export function TimeChart({ traces, range, cursor, height = 260, yTitle, hlines = [], alerts = [], clip = true }: Props) {
  const c = useThrottled(cursor, 200)

  const data = useMemo(
    () =>
      traces
        .filter((t) => t.series)
        .map((t) => {
          const s = t.series!
          const ts = times(s)
          let end = ts.length
          if (clip && c != null) {
            let lo = 0
            let hi = ts.length
            while (lo < hi) {
              const mid = (lo + hi) >> 1
              if (ts[mid] <= c) lo = mid + 1
              else hi = mid
            }
            end = lo
          }
          return {
            x: s.t.slice(0, end), y: s.v.slice(0, end), name: t.name, type: 'scatter' as const, mode: 'lines' as const,
            line: { color: t.color, width: t.width ?? 1.6, dash: t.dash ?? 'solid' },
            connectgaps: false, fill: t.fillPrev ? ('tonexty' as const) : ('none' as const),
            fillcolor: 'rgba(100,116,139,0.14)',
            hovertemplate: `${t.name}: %{y:.1f}<extra></extra>`,
          }
        }),
    [traces, c, clip],
  )

  const layout = useMemo(() => {
    const border = css('--border', '#E2E8F0')
    const muted = css('--muted', '#64748B')
    const shapes: object[] = []
    if (c != null && range && c >= range[0] && c <= range[1]) {
      shapes.push({ type: 'line', xref: 'x', yref: 'paper', x0: ist(c), x1: ist(c), y0: 0, y1: 1, line: { color: css('--accent', '#0284C7'), width: 1.5 } })
    }
    for (const a of alerts.slice(0, 60)) {
      const t = alertMs(a)
      if (clip && c != null && t > c) continue
      shapes.push({ type: 'line', xref: 'x', yref: 'paper', x0: ist(t), x1: ist(t), y0: 0, y1: 1, line: { color: '#94A3B8', width: 1, dash: 'dot' } })
    }
    for (const h of hlines) {
      shapes.push({ type: 'line', xref: 'paper', yref: 'y', x0: 0, x1: 1, y0: h.y, y1: h.y, line: { color: '#B45309', width: 1, dash: 'dash' } })
    }
    return {
      height, margin: { l: 48, r: 12, t: 8, b: 30 }, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: 'Inter, system-ui, sans-serif', size: 11, color: muted },
      xaxis: { type: 'date' as const, range: range ? [ist(range[0]), ist(range[1])] : undefined, gridcolor: border, linecolor: border },
      yaxis: { title: { text: yTitle }, gridcolor: border, zerolinecolor: border },
      legend: { orientation: 'h' as const, y: 1.14, x: 0 },
      shapes, hovermode: 'x unified' as const,
      annotations: hlines.map((h) => ({ xref: 'paper' as const, x: 1, xanchor: 'right' as const, yref: 'y' as const, y: h.y, text: h.label, showarrow: false, font: { color: '#B45309', size: 10 }, yshift: 8 })),
    }
  }, [c, range, height, yTitle, hlines, alerts, clip])

  if (!data.length) return <p className="unavailable">No data for this chart.</p>
  return <Plot data={data} layout={layout} config={{ displayModeBar: false, responsive: true }} useResizeHandler style={{ width: '100%', height }} />
}
