import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useBackend } from '../api/client'
import { useSession } from '../context/Session'
import { DemoButton, DemoOverlay } from './Demo'
import { Recorder } from './Recorder'
import { StatusChip } from './ui'

const FOOTER = 'SIMULATED data is labelled. The 3D transformer is a generic cutaway drawn in code, not a specific unit.'
const MODE_LABEL: Record<string, string> = { full: 'full data', meter_only: 'meter only', data_only: 'data only', snapshot: 'records' }

function Mark() {
  // Two traces and the gap between them, in ink: the idea of the product in 38 pixels.
  return (
    <svg className="brand__mark" viewBox="0 0 38 38" aria-hidden="true">
      <defs>
        <pattern id="mk" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="4" stroke="#fff" strokeWidth="1.3" /></pattern>
      </defs>
      <rect x="0" y="0" width="38" height="38" rx="12" fill="#0b0b0c" />
      <path d="M7 26 C 13 12, 23 12, 32 19 L 32 24 C 23 18, 13 19, 7 31 Z" fill="url(#mk)" fillOpacity="0.75" />
      <path d="M7 26 C 13 12, 23 12, 32 19" fill="none" stroke="#9a9da3" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M7 31 C 13 19, 23 18, 32 24" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  )
}

const ICONS: Record<string, string> = {
  '/': 'M3 11l9-8 9 8M5 10v10h14V10',
  '/records': 'M4 6h16M4 12h16M4 18h10',
  '/physics': 'M3 18c4 0 5-12 9-12s5 12 9 12',
  '/temps': 'M10 4a2 2 0 014 0v9.2a4 4 0 11-4 0V4z',
  '/modules': 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
  '/alerts': 'M6 16v-5a6 6 0 1112 0v5l1.5 2h-15L6 16zM10 21h4',
  '/profile': 'M4 7h10M18 7h2M4 17h2M10 17h10M14 4v6M6 14v6',
  '/import': 'M12 16V4m0 0l-4 4m4-4l4 4M4 20h16',
  '/data-health': 'M3 12h4l2-6 4 12 2-6h6',
  '/field-data': 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zm0 0v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6m-16 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6',
  '/self-test': 'M12 21a9 9 0 100-18 9 9 0 000 18zM8 12l3 3 5-6',
  '/reports': 'M7 3h7l4 4v14H7zM14 3v4h4M9 12h6M9 16h6',
  '/about': 'M12 21a9 9 0 100-18 9 9 0 000 18zM12 11v6M12 8h.01',
}

function NavIcon({ to }: { to: string }) {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d={ICONS[to] ?? ICONS['/about']} /></svg>
}

export function Layout() {
  const s = useSession()
  const backend = useBackend()
  const qc = useQueryClient()
  const loc = useLocation()
  const snapshot = s.run?.mode === 'snapshot'
  const onField = loc.pathname === '/field-data'

  const groups: [string, [string, string][]][] = [
    ['Monitor', [
      ['/', 'Overview'],
      ...(snapshot ? ([['/records', 'Records']] as [string, string][]) : []),
      ['/physics', 'Physics'],
      ['/temps', 'Loading & Temperatures'],
      ['/modules', 'Failure Modules'],
      ['/alerts', 'Alerts & Maintenance'],
    ]],
    ['Data', [
      ['/profile', 'Transformer profile'],
      ['/import', 'Import'],
      ['/data-health', 'Data Health'],
      ['/field-data', 'Real Field Data'],
    ]],
    ['Deliver', [
      ['/self-test', 'Self-Test'],
      ['/reports', 'Reports'],
      ['/about', 'About'],
    ]],
  ]

  // Keyboard: space play/pause, arrows step an hour (shift: a day), N / P jump between alerts. Typing in a field is left alone;
  // a focused button does not swallow the space bar (its own activation is cancelled so the replay still toggles once).
  useEffect(() => {
    const typing = (t: HTMLElement) => ['INPUT', 'SELECT', 'TEXTAREA'].includes(t.tagName) || t.isContentEditable
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (typing(t) || e.ctrlKey || e.metaKey || e.altKey || !s.bounds) return
      if (e.key === ' ') { e.preventDefault(); s.togglePlay() }
      else if (e.key === 'ArrowRight') { e.preventDefault(); s.stepBy(e.shiftKey ? 86400_000 : 3600_000) }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); s.stepBy(e.shiftKey ? -86400_000 : -3600_000) }
      else if (t.tagName !== 'BUTTON' && (e.key === 'n' || e.key === 'N')) s.nextAlert()
      else if (t.tagName !== 'BUTTON' && (e.key === 'p' || e.key === 'P')) s.prevAlert()
    }
    const onKeyUp = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (e.key === ' ' && !typing(t) && s.bounds) e.preventDefault()          // stops a focused button from also clicking
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('keyup', onKeyUp)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('keyup', onKeyUp) }
  }, [s])

  const health = s.now?.health
  const a = s.run?.asset
  const assetLine = a
    ? [a.rating_kVA ? `${Math.round(Number(a.rating_kVA))} kVA` : null, a.lv_voltage_V ? `${Math.round(Number(a.lv_voltage_V))} V` : null, a.cooling ? String(a.cooling) : null]
        .filter(Boolean).join('   ') + (a.nameplate_source === 'estimated' ? ' (estimated)' : '')
    : 'Loading asset…'

  return (
    <div className="shell">
      <a className="skip" href="#main">Skip to content</a>
      <aside className="sidebar">
        <div className="brand">
          <Mark />
          <div className="brand__text">
            <strong>{String(a?.name ?? 'Digital twin')}</strong>
            <span>{assetLine}</span>
          </div>
        </div>
        <nav className="nav" aria-label="Pages">
          {groups.map(([group, items]) => (
            <div key={group} style={{ display: 'contents' }}>
              <span className="nav__group">{group}</span>
              {items.map(([to, label]) => <NavLink key={to} to={to} end={to === '/'}><NavIcon to={to} />{label}</NavLink>)}
            </div>
          ))}
        </nav>
        <p className="sidebar__foot">Physics says what should happen, data says what is happening, and the AI watches the gap.</p>
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
              {s.datasets.map((d) => <option key={d.dataset_id} value={d.dataset_id}>{d.name}</option>)}
            </select>
          </label>
          {s.run && <span className="chip chip--mode" title="What the dataset supports">{MODE_LABEL[s.run.mode] ?? s.run.mode}</span>}
          {health?.band && <StatusChip band={health.band} text={`Health ${Math.round(health.score ?? 0)}`} />}
          {!s.bounds && s.run && <span className="muted">{snapshot ? 'Records without time: no replay.' : 'No time axis: replay unavailable.'}</span>}
          <span className="topbar__spacer" />
          <span className="keyhint" title="Keyboard shortcuts"><kbd>Space</kbd> play <kbd>←</kbd><kbd>→</kbd> step <kbd>N</kbd> next alert</span>
          <DemoButton />
        </header>

        <main id="main" className="content">
          <Outlet />
        </main>
        <footer className="footer">{FOOTER}</footer>
      </div>
      <Recorder />
      <DemoOverlay />
    </div>
  )
}
