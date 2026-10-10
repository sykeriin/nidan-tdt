import Plotly from 'plotly.js-basic-dist-min'
import createPlotlyComponent from 'react-plotly.js/factory'

const Plot = createPlotlyComponent(Plotly)

export interface XYTrace {
  name: string
  x: number[]
  y: (number | null)[]
  color: string
  dash?: 'solid' | 'dash' | 'dot'
}

/** Plain numeric-x line chart (minutes after a load step, and similar). */
export function XYChart({ traces, height = 260, xTitle, yTitle, vlines = [], logY = false }: {
  traces: XYTrace[]
  height?: number
  xTitle?: string
  yTitle?: string
  vlines?: { x: number; label: string }[]
  logY?: boolean
}) {
  const border = 'rgba(11,11,12,0.07)'
  return (
    <Plot
      data={traces.map((t) => ({
        x: t.x, y: t.y, name: t.name, type: 'scatter' as const, mode: 'lines' as const,
        line: { color: t.color, width: 1.8, dash: t.dash ?? 'solid' }, hovertemplate: `${t.name}: %{y:.1f}<extra></extra>`,
      }))}
      layout={{
        height, margin: { l: 48, r: 12, t: 8, b: 40 }, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
        font: { family: 'Barlow, system-ui, sans-serif', size: 12, color: '#8a8d93' },
        hoverlabel: { bgcolor: '#ffffff', bordercolor: '#d9dadd', font: { color: '#0b0b0c' } },
        xaxis: { title: { text: xTitle }, gridcolor: border, linecolor: border },
        yaxis: { title: { text: yTitle }, gridcolor: border, zerolinecolor: border, type: logY ? ('log' as const) : ('linear' as const) },
        legend: { orientation: 'h', y: 1.14, x: 0 }, hovermode: 'x unified',
        shapes: vlines.map((v) => ({ type: 'line' as const, xref: 'x' as const, yref: 'paper' as const, x0: v.x, x1: v.x, y0: 0, y1: 1, line: { color: 'rgba(11,11,12,0.28)', width: 1, dash: 'dot' as const } })),
        annotations: vlines.map((v) => ({ xref: 'x' as const, yref: 'paper' as const, x: v.x, y: 0.02, text: v.label, showarrow: false, xanchor: 'left' as const, font: { size: 11, color: '#8a8d93' } })),
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: '100%', height }}
    />
  )
}
