import { useState } from 'react'
import { reportUrl } from '../api/client'
import { Gate } from '../components/Gate'
import { Card, DataTable, Note, PageTitle } from '../components/ui'
import { fmt } from '../lib/series'

function download(name: string, text: string, type = 'text/csv') {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

const csvCell = (v: unknown) => {
  const s = v == null ? '' : String(v)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}
const toCsv = (cols: string[], rows: Record<string, unknown>[]) => [cols.join(','), ...rows.map((r) => cols.map((c) => csvCell(r[c])).join(','))].join('\n')

export default function Reports() {
  const [pdfMsg, setPdfMsg] = useState<string | null>(null)
  return (
    <>
      <PageTitle title="Reports" sub="Download the run, its alerts and the lead-time table." />
      <Gate timeSeries={false}>
        {(run) => {
          const withLead = run.analysis.alerts.filter((a) => a.lead_time_h != null)
          const leadRows = withLead.map((a) => ({ type: a.type, module: a.module, detector: a.detector, origin: a.origin, lead_time_h: a.lead_time_h, timestamp: a.timestamp }))
          const pdf = async () => {
            setPdfMsg(null)
            try {
              const res = await fetch(reportUrl(run.dataset_id))
              if (!res.ok) {
                const body = await res.json().catch(() => null)
                setPdfMsg(body?.detail ?? `The report could not be created (${res.status}).`)
                return
              }
              const url = URL.createObjectURL(await res.blob())
              const a = document.createElement('a')
              a.href = url
              a.download = `${run.dataset_id}-report.pdf`
              a.click()
              URL.revokeObjectURL(url)
            } catch {
              setPdfMsg('Backend offline: start the server.')
            }
          }
          return (
            <>
              <Card title="Downloads">
                <div className="row">
                  <button className="btn btn--primary" type="button" onClick={pdf}>Download PDF report</button>
                  <button className="btn" type="button" onClick={() => download(`${run.dataset_id}-alerts.csv`, toCsv(['id', 'timestamp', 'module', 'type', 'severity', 'origin', 'detector', 'value', 'threshold', 'lead_time_h', 'simulated', 'explanation'], run.analysis.alerts as unknown as Record<string, unknown>[]))}>
                    Alerts (CSV)
                  </button>
                  <button className="btn" type="button" onClick={() => download(`${run.dataset_id}-recommendations.csv`, toCsv(['id', 'action', 'test', 'urgency', 'rationale', 'alert_id', 'standard_ref'], run.analysis.recommendations as unknown as Record<string, unknown>[]))}>
                    Recommendations (CSV)
                  </button>
                </div>
                {pdfMsg && <div style={{ marginTop: 12 }}><Note tone="warn">PDF report: {pdfMsg}</Note></div>}
                <p className="muted" style={{ marginTop: 8 }}>
                  CSV exports contain the analysis results. Trend data in the charts is downsampled for display; the full-resolution table stays on the server.
                </p>
              </Card>
              <Card title="Key figures">
                <dl className="kv">
                  <dt>Dataset</dt><dd>{run.name}</dd>
                  <dt>Mode</dt><dd>{run.mode}</dd>
                  <dt>Health Index (end of data)</dt><dd>{fmt(run.analysis.health.score, 0)} · {run.analysis.health.band}</dd>
                  <dt>Remaining life</dt><dd>{String(run.summary.rul_display ?? '—')}</dd>
                  <dt>Alerts</dt><dd>{run.analysis.alerts.length}</dd>
                  <dt>Recommendations</dt><dd>{run.analysis.recommendations.length}</dd>
                </dl>
              </Card>
              <Card title="Lead time vs plain thresholds">
                {leadRows.length ? (
                  <DataTable table={{ columns: ['type', 'module', 'detector', 'origin', 'lead_time_h', 'timestamp'], rows: leadRows }} />
                ) : (
                  <p className="muted">No lead time recorded for this dataset. It is computed for the generated scenarios only, where the injected fault time is known.</p>
                )}
              </Card>
            </>
          )
        }}
      </Gate>
    </>
  )
}
