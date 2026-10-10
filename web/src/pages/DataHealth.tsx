import type { ReactNode } from 'react'
import { Gate } from '../components/Gate'
import { Card, DataTable, Note, PageTitle } from '../components/ui'

export const CAP_INFO: Record<string, { label: string; needs: string }> = {
  thermal_twin: { label: 'Thermal twin', needs: 'current (or kVA / loading %) and ambient temperature' },
  residual_fidelity: { label: 'Residual and fidelity', needs: 'a measured top-oil temperature plus the twin' },
  wti_check: { label: 'Winding temperature check', needs: 'a winding temperature channel (WTI)' },
  unbalance: { label: 'Current unbalance', needs: 'measured R, Y and B currents' },
  voltage_quality: { label: 'Voltage quality', needs: 'R, Y and B phase voltages' },
  neutral_measured: { label: 'Measured neutral current', needs: 'a neutral current channel (IN)' },
  oil_leak_theft: { label: 'Oil leak vs theft', needs: 'an oil level channel over time' },
  through_fault: { label: 'Through-fault stress', needs: 'an event log' },
  breathing_index: { label: 'Breathing stress (experimental)', needs: 'humidity and temperatures' },
  ageing_rul: { label: 'Ageing and remaining life', needs: 'the thermal twin running over time' },
  lead_time_eval: { label: 'Lead-time evaluation', needs: 'ground-truth labels (generated scenarios only)' },
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)

export function CapabilityList({ caps }: { caps: Record<string, boolean> }) {
  return (
    <ul className="caps">
      {Object.entries(caps).map(([k, on]) => (
        <li key={k}>
          <span aria-hidden style={{ color: on ? 'var(--ok-text)' : 'var(--stale-text)', fontWeight: 700 }}>{on ? '✓' : '✕'}</span>
          <span>
            {CAP_INFO[k]?.label ?? k}
            {!on && <span className="muted"> — needs {CAP_INFO[k]?.needs ?? 'more data'}</span>}
          </span>
        </li>
      ))}
    </ul>
  )
}

export function CountsTable({ counts }: { counts: Record<string, unknown> }) {
  const rows = Object.entries(counts).map(([code, n]) => ({ code, rows: Number(n) }))
  if (!rows.length) return <p className="muted">No data-quality flags.</p>
  return <DataTable table={{ columns: ['code', 'rows'], rows }} />
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <Card title={title}>{children}</Card>
}

export default function DataHealth() {
  return (
    <>
      <PageTitle title="Data Health" sub="What the adapter read, cleaned, converted and derived, and what that lets the twin do." />
      <Gate timeSeries={false}>
        {(run) => {
          const hr = run.health_report
          const tables = Array.isArray(hr.tables) ? (hr.tables as Record<string, unknown>[]) : []
          const flags = isObj(hr.flag_counts_final) ? hr.flag_counts_final : isObj(hr.flag_counts) ? hr.flag_counts : {}
          const verdict = isObj(hr.plausibility) && isObj(hr.plausibility.verdict) ? hr.plausibility.verdict : null
          const warnings = Array.isArray(hr.warnings) ? (hr.warnings as string[]) : []
          const derived = Array.isArray(hr.derived) ? (hr.derived as unknown[]) : []
          const enrichment = Array.isArray(hr.enrichment) ? (hr.enrichment as string[]) : []
          const span = Array.isArray(hr.time_span) ? (hr.time_span as string[]) : null
          const source = String(run.asset.nameplate_source ?? hr.nameplate_source ?? 'unknown')

          return (
            <>
              <div className="grid grid--4">
                <Card title="Mode"><div className="big">{run.mode.replace('_', '-')}</div></Card>
                <Card title="Rows">
                  <div className="big">{String(hr.rows_after_cleaning ?? run.rows_in_range)}</div>
                  <p className="muted">after cleaning{run.downsampled ? ' (charts are downsampled)' : ''}</p>
                </Card>
                <Card title="Time span / interval">
                  <p className="num">{span ? `${span[0].slice(0, 16)} → ${span[1].slice(0, 16)}` : `${run.start?.slice(0, 16) ?? '—'} → ${run.end?.slice(0, 16) ?? '—'}`}</p>
                  <p className="muted">{String(hr.interval ?? 'interval unknown')}</p>
                </Card>
                <Card title="Nameplate source">
                  <div className="big" style={{ fontSize: 18 }}>{source}</div>
                  {source === 'estimated' && <p style={{ color: 'var(--crit-text)', fontWeight: 600 }}>Estimated from data: rating-dependent values are assumptions.</p>}
                  <p className="muted">{String(run.asset.rating_kVA ?? '—')} kVA · {String(run.asset.lv_voltage_V ?? '—')} V · {String(run.asset.i_rated_A ?? '—')} A</p>
                </Card>
              </div>

              {warnings.map((w) => <Note key={w} tone="warn">{w}</Note>)}

              <Section title="Capability matrix">
                <CapabilityList caps={run.capabilities} />
              </Section>

              {verdict && (
                <Section title="Sensor plausibility (physics check)">
                  <ul className="caps">
                    {Object.entries(verdict).map(([ch, v]) => (
                      <li key={ch}>
                        <strong>{ch}</strong>: {String(v)}
                        {ch === 'OTI_C' && v === 'suspect' && <span className="muted"> — the rise over ambient is too small for an oil-filled transformer; check the sensor placement.</span>}
                      </li>
                    ))}
                  </ul>
                </Section>
              )}

              <Section title="Data-quality flags"><CountsTable counts={flags} /></Section>

              {tables.length > 0 && (
                <Section title="Files read">
                  <DataTable table={{ columns: ['name', 'role', 'rows_read', 'encoding', 'delimiter'], rows: tables as Record<string, unknown>[] }} />
                </Section>
              )}

              {(derived.length > 0 || enrichment.length > 0) && (
                <Section title="Derived and enriched channels">
                  <ul>
                    {derived.map((d, i) => <li key={`d${i}`}>{typeof d === 'string' ? d : JSON.stringify(d)}</li>)}
                    {enrichment.map((e) => <li key={e}>{e}</li>)}
                  </ul>
                </Section>
              )}

              <Section title="Everything else the adapter reported">
                <pre className="num" style={{ whiteSpace: 'pre-wrap', fontSize: 12, margin: 0, maxHeight: 280, overflow: 'auto' }}>
                  {JSON.stringify(Object.fromEntries(Object.entries(hr).filter(([k]) => !['tables', 'flag_counts', 'flag_counts_final', 'capabilities'].includes(k))), null, 1)}
                </pre>
              </Section>
            </>
          )
        }}
      </Gate>
    </>
  )
}
