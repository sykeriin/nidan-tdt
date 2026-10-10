import type { ReactNode } from 'react'
import type { Alert, Table } from '../api/client'
import type { Band } from '../lib/derive'
import { fmt, fmtTime } from '../lib/series'

export function Card({ title, children, className = '', aside }: { title?: string; children: ReactNode; className?: string; aside?: ReactNode }) {
  return (
    <section className={`card ${className}`}>
      {(title || aside) && (
        <header className="card__head">
          {title && <h3>{title}</h3>}
          {aside}
        </header>
      )}
      {children}
    </section>
  )
}

export function PageTitle({ title, sub }: { title: string; sub?: ReactNode }) {
  return (
    <div className="page-title">
      <h1>{title}</h1>
      {sub && <p className="muted">{sub}</p>}
    </div>
  )
}

const BAND_META: Record<Band, { icon: string; word: string }> = {
  green: { icon: '✓', word: 'Normal' },
  yellow: { icon: '▲', word: 'Watch' },
  red: { icon: '✕', word: 'Critical' },
}

/** Status is always icon + word + colour, never colour alone. */
export function StatusChip({ band, text }: { band: Band | 'grey'; text?: string }) {
  if (band === 'grey') {
    return <span className="chip chip--grey"><span aria-hidden>?</span>{text ?? 'No data'}</span>
  }
  const m = BAND_META[band]
  return <span className={`chip chip--${band}`}><span aria-hidden>{m.icon}</span>{text ?? m.word}</span>
}

export const bandLabel = (b: Band | null) => (b ? b[0].toUpperCase() + b.slice(1) : '—')

export function Unavailable({ children }: { children: ReactNode }) {
  return <p className="unavailable">Not available: {children}</p>
}

export function Note({ tone = 'info', children }: { tone?: 'info' | 'warn' | 'error'; children: ReactNode }) {
  return <div className={`note note--${tone}`} role={tone === 'error' ? 'alert' : undefined}>{children}</div>
}

export function Skeleton({ h = 120 }: { h?: number }) {
  return <div className="skeleton" style={{ height: h }} aria-busy="true" />
}

export function SimulatedTag() {
  return <span className="tag-sim">SIMULATED</span>
}

export function HealthGauge({ score, band, capped }: { score: number | null; band: Band | null; capped: boolean }) {
  const pct = score == null ? 0 : Math.max(0, Math.min(100, score)) / 100
  const R = 54
  const C = Math.PI * R
  return (
    <div className="gauge" role="img" aria-label={`Health index ${score == null ? 'unavailable' : Math.round(score)} out of 100, ${bandLabel(band)}`}>
      <svg viewBox="0 0 140 84" width="100%">
        <path d="M16 74 A54 54 0 0 1 124 74" fill="none" stroke="var(--border)" strokeWidth="12" strokeLinecap="round" />
        <path
          d="M16 74 A54 54 0 0 1 124 74" fill="none" strokeWidth="12" strokeLinecap="round"
          stroke={band ? `var(--band-${band})` : 'var(--stale)'}
          strokeDasharray={`${C * pct} ${C}`}
        />
      </svg>
      <div className="gauge__value num">{score == null ? '—' : Math.round(score)}</div>
      {capped && <p className="gauge__cap">Capped at 40 by a critical alarm</p>}
    </div>
  )
}

const SUB_LABEL: Record<string, string> = {
  thermal: 'Thermal', ageing: 'Ageing', loading: 'Loading', electrical: 'Electrical quality',
  integrity: 'Integrity', fault_stress: 'Fault stress',
}

export function SubScoreBars({ components, weights }: { components: Record<string, number>; weights: Record<string, number> }) {
  const keys = Object.keys(SUB_LABEL)
  return (
    <ul className="subscores">
      {keys.map((k) => {
        const v = components[k]
        const available = v != null
        const band: Band = !available ? 'green' : v >= 80 ? 'green' : v >= 60 ? 'yellow' : 'red'
        return (
          <li key={k}>
            <span className="subscores__label">{SUB_LABEL[k]}</span>
            <span className="subscores__bar" aria-hidden>
              <span style={{ width: `${available ? v : 0}%`, background: available ? `var(--band-${band})` : 'transparent' }} />
            </span>
            <span className="num subscores__val">{available ? Math.round(v) : '—'}</span>
            <span className="subscores__w muted">{available && weights[k] != null ? `${Math.round(weights[k] * 100)}%` : 'n/a'}</span>
          </li>
        )
      })}
    </ul>
  )
}

const SEV_BAND: Record<string, Band> = { critical: 'red', warning: 'yellow', info: 'green' }

export function AlertItem({ alert, onClick }: { alert: Alert; onClick?: () => void }) {
  const sensor = alert.origin === 'sensor'
  return (
    <li className={`alert ${sensor ? 'alert--sensor' : ''}`}>
      <button type="button" className="alert__btn" onClick={onClick} disabled={!onClick}>
        <span className="alert__top">
          {sensor ? <span className="chip chip--sensor">ⓘ Sensor</span> : <StatusChip band={SEV_BAND[alert.severity] ?? 'green'} text={alert.severity} />}
          <strong>{alert.type.replace(/_/g, ' ')}</strong>
          {alert.simulated && <SimulatedTag />}
          <span className="muted num alert__time">{fmtTime(alert.timestamp)}</span>
        </span>
        <span className="alert__text">{alert.explanation}</span>
        {sensor && <span className="alert__sensor">Data fault: check the device, not the transformer.</span>}
        {alert.lead_time_h != null && <span className="muted">Lead time {fmt(alert.lead_time_h)} h vs plain thresholds</span>}
      </button>
    </li>
  )
}

export function DataTable({ table, limit = 200, format }: { table: Table; limit?: number; format?: (col: string, v: unknown) => ReactNode }) {
  const rows = table.rows.slice(0, limit)
  const show = (c: string, v: unknown): ReactNode => {
    if (format) {
      const f = format(c, v)
      if (f !== undefined) return f
    }
    if (v == null) return '—'
    if (typeof v === 'number') return Number.isInteger(v) ? v : v.toFixed(2)
    if (typeof v === 'boolean') return v ? 'yes' : 'no'
    return String(v)
  }
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>{table.columns.map((c) => <th key={c} scope="col">{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{table.columns.map((c) => <td key={c} className={typeof r[c] === 'number' ? 'num' : ''}>{show(c, r[c])}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {table.rows.length > limit && <p className="muted">Showing the first {limit} of {table.rows.length} rows.</p>}
    </div>
  )
}
