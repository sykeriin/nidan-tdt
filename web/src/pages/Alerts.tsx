import { useMemo, useState } from 'react'
import { Gate } from '../components/Gate'
import { Card, PageTitle, SimulatedTag, StatusChip } from '../components/ui'
import { useSession } from '../context/Session'
import { fmt, fmtTime } from '../lib/series'

const LIMIT = 300
const SEV: Record<string, 'green' | 'yellow' | 'red'> = { critical: 'red', warning: 'yellow', info: 'green' }
const URGENCY: Record<string, string> = { immediate: 'Immediate', '24h': 'Within 24 h', '7d': 'Within 7 days', next_scheduled: 'Next scheduled' }

export default function Alerts() {
  const s = useSession()
  const [sev, setSev] = useState('all')
  const [mod, setMod] = useState('all')
  const [origin, setOrigin] = useState('all')
  const [det, setDet] = useState('all')
  const [focus, setFocus] = useState<string | null>(null)

  const all = s.alerts
  const rows = useMemo(
    () => all.filter((a) => (sev === 'all' || a.severity === sev) && (mod === 'all' || a.module === mod) && (origin === 'all' || a.origin === origin) && (det === 'all' || a.detector === det)),
    [all, sev, mod, origin, det],
  )
  const opts = (key: 'module' | 'detector') => [...new Set(all.map((a) => a[key]))].sort()

  return (
    <>
      <PageTitle title="Alerts & Maintenance" sub="Every alert says whether it is an asset problem or a sensor/data fault, and which test to run." />
      <Gate timeSeries={false}>
        {(run) => {
          const recById = new Map(run.analysis.recommendations.map((r) => [r.id, r]))
          const select = (label: string, value: string, set: (v: string) => void, options: string[]) => (
            <label className="muted">
              {label}
              <select value={value} onChange={(e) => set(e.target.value)}>
                <option value="all">All</option>
                {options.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            </label>
          )
          return (
            <>
              <Card title={`Alerts (${rows.length}${rows.length !== all.length ? ` of ${all.length}` : ''})`}>
                <div className="row" style={{ marginBottom: 12 }}>
                  {select('Severity', sev, setSev, ['critical', 'warning', 'info'])}
                  {select('Module', mod, setMod, opts('module'))}
                  {select('Origin', origin, setOrigin, ['asset', 'sensor'])}
                  {select('Detector', det, setDet, opts('detector'))}
                </div>
                {rows.length === 0 ? (
                  <p className="muted">No alerts match.</p>
                ) : (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Time (IST)</th><th>Severity</th><th>Origin</th><th>Module</th><th>Type</th><th>Detector</th>
                          <th>Value / limit</th><th>Lead time</th><th>Explanation</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.slice(0, LIMIT).map((a) => (
                          <tr key={a.id} id={`alert-${a.id}`} style={focus === a.id ? { background: '#E0F2FE' } : undefined}>
                            <td className="num">
                              {s.bounds ? (
                                <button type="button" className="btn" onClick={() => s.setCursor(Date.parse(a.timestamp))} title="Jump the replay here">{fmtTime(a.timestamp)}</button>
                              ) : fmtTime(a.timestamp)}
                            </td>
                            <td><StatusChip band={SEV[a.severity] ?? 'green'} text={a.severity} /></td>
                            <td>{a.origin === 'sensor' ? <span className="chip chip--sensor">ⓘ Sensor</span> : 'Asset'}</td>
                            <td>{a.module.replace('_', ' ')}</td>
                            <td>{a.type.replace(/_/g, ' ')} {a.simulated && <SimulatedTag />}</td>
                            <td>{a.detector}</td>
                            <td className="num">{fmt(a.value, 2)} / {fmt(a.threshold, 2)}</td>
                            <td className="num">{a.lead_time_h != null ? `${fmt(a.lead_time_h)} h` : '—'}</td>
                            <td>
                              {a.explanation}
                              {a.origin === 'sensor' && <strong style={{ display: 'block', color: 'var(--stale-text)' }}>Data fault: check the device, not the transformer.</strong>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {rows.length > LIMIT && <p className="muted">Showing the first {LIMIT} of {rows.length}; narrow the filters to see the rest.</p>}
                  </div>
                )}
              </Card>

              <Card title="Maintenance recommendations">
                {run.analysis.recommendations.length === 0 ? (
                  <p className="muted">No recommendations: nothing in this run needs action.</p>
                ) : (
                  <div className="table-wrap">
                    <table className="table">
                      <thead><tr><th>Action</th><th>Test</th><th>Urgency</th><th>Why</th><th>Reference</th><th>Alert</th></tr></thead>
                      <tbody>
                        {run.analysis.recommendations.slice(0, LIMIT).map((r) => (
                          <tr key={r.id}>
                            <td><strong>{r.action}</strong></td>
                            <td>{r.test ?? '—'}</td>
                            <td>{URGENCY[r.urgency] ?? r.urgency}</td>
                            <td>{r.rationale}</td>
                            <td>{r.standard_ref ?? '—'}</td>
                            <td>
                              <a href={`#/alerts`} onClick={(e) => { e.preventDefault(); setFocus(r.alert_id); document.getElementById(`alert-${r.alert_id}`)?.scrollIntoView({ block: 'center' }) }}>
                                {recById.has(r.id) ? r.alert_id : '—'}
                              </a>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <p className="muted" style={{ marginTop: 8 }}>
                  Standards references (IS 1180, IEC 60076-7, tan-delta testing) are marked to verify against the primary text before use.
                </p>
              </Card>
            </>
          )
        }}
      </Gate>
    </>
  )
}
