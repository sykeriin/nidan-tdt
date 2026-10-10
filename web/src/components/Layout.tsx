import { useQueryClient } from '@tanstack/react-query'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useBackend } from '../api/client'
import { SPEEDS, useSession } from '../context/Session'
import { fmtTime } from '../lib/series'
import { StatusChip } from './ui'

const FOOTER = 'SIMULATED data is labelled. 3D model: Showdoze (Sketchfab), CC-BY-NC 4.0.'
const MODE_LABEL: Record<string, string> = { full: 'full', meter_only: 'meter-only', data_only: 'data-only', snapshot: 'snapshot' }

export function Layout() {
  const s = useSession()
  const backend = useBackend()
  const qc = useQueryClient()
  const snapshot = s.run?.mode === 'snapshot'
  // The field-data page always shows the Kaggle unit, not the selected dataset.
  const onField = useLocation().pathname === '/field-data'

  const nav: [string, string][] = [
    ['/', 'Overview'],
    ...(snapshot ? ([['/records', 'Records']] as [string, string][]) : []),
    ['/temps', 'Loading & Temperatures'],
    ['/modules', 'Failure Modules'],
    ['/alerts', 'Alerts & Maintenance'],
    ['/import', 'Import'],
    ['/data-health', 'Data Health'],
    ['/field-data', 'Real Field Data'],
    ['/self-test', 'Self-Test'],
    ['/reports', 'Reports'],
    ['/about', 'About'],
  ]

  const health = s.now?.health
  const a = s.run?.asset
  const assetLine = a
    ? [a.rating_kVA ? `${Math.round(Number(a.rating_kVA))} kVA` : null, a.lv_voltage_V ? `${Math.round(Number(a.lv_voltage_V))} V` : null, a.cooling ? String(a.cooling) : null]
        .filter(Boolean).join(' · ') + (a.nameplate_source === 'estimated' ? ' (estimated)' : '')
    : 'Loading asset…'
  return (
    <div className="shell">
      <a className="skip" href="#main">Skip to content</a>
      <aside className="sidebar">
        <div className="brand">
          <strong>{String(s.run?.asset?.name ?? 'Transformer twin')}</strong>
          <span>{assetLine}</span>
        </div>
        <nav className="nav" aria-label="Pages">
          {nav.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === '/'}>{label}</NavLink>
          ))}
        </nav>
        <p className="sidebar__foot">PowerNext-AI 2026 · Track 02<br />Physics says what should happen, data says what is happening, the AI watches the gap.</p>
      </aside>

      <div className="main">
        {backend.isError && (
          <div className="banner banner--error" role="alert">
            Backend offline: start the server (uvicorn server.app:app --port 8000).
            <button className="btn" type="button" onClick={() => qc.invalidateQueries()}>Retry</button>
          </div>
        )}
        {s.simulated && !onField && <div className="banner banner--sim">SIMULATED: {s.label}</div>}
        {s.run?.asset?.nameplate_source === 'estimated' && (
          <div className="banner banner--est">Nameplate estimated from the data: rating-dependent values are assumptions.</div>
        )}

        <header className="topbar">
          <label>
            Dataset
            <select value={s.datasetId ?? ''} onChange={(e) => s.setDatasetId(e.target.value)} aria-label="Dataset">
              {s.datasets.map((d) => (
                <option key={d.dataset_id} value={d.dataset_id}>{d.name}</option>
              ))}
            </select>
          </label>
          {s.run && <span className="chip chip--mode">Mode: {MODE_LABEL[s.run.mode] ?? s.run.mode}</span>}
          {health?.band && (
            <StatusChip band={health.band} text={`Health ${Math.round(health.score ?? 0)}`} />
          )}
          {s.bounds && s.cursor != null ? (
            <div className="replay">
              <button className="btn btn--primary" type="button" onClick={s.togglePlay} aria-label={s.playing ? 'Pause replay' : 'Play replay'}>
                {s.playing ? '❚❚ Pause' : '▶ Play'}
              </button>
              <input
                type="range" min={s.bounds.start} max={s.bounds.end} step={900_000} value={s.cursor}
                onChange={(e) => s.setCursor(Number(e.target.value))} aria-label="Replay position"
              />
              <select value={s.speed} onChange={(e) => s.setSpeed(Number(e.target.value))} aria-label="Replay speed">
                {SPEEDS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
              </select>
              <button className="btn" type="button" onClick={s.nextAlert} aria-label="Jump to next alert">Next alert ⏭</button>
              <span className="replay__time">{fmtTime(s.cursor)} IST</span>
            </div>
          ) : (
            s.run && <span className="muted">{snapshot ? 'Records without time: no replay.' : 'No time axis: replay unavailable.'}</span>
          )}
        </header>

        <main id="main" className="content">
          <Outlet />
        </main>
        <footer className="footer">{FOOTER}</footer>
      </div>
    </div>
  )
}
