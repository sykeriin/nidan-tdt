import { useRef } from 'react'
import { reportHref } from '../api/client'
import { Gate } from '../components/Gate'
import { Card, DataTable, PageTitle } from '../components/ui'
import { fmt } from '../lib/series'

export default function Reports() {
  const frame = useRef<HTMLIFrameElement>(null)
  return (
    <>
      <PageTitle title="Reports" sub="One self-contained page with the charts drawn in, plus the full time series and a machine-readable export." />
      <Gate timeSeries={false}>
        {(run) => {
          const withLead = run.analysis.alerts.filter((a) => a.lead_time_h != null)
          const leadRows = withLead.map((a) => ({ type: a.type, module: a.module, detector: a.detector, origin: a.origin, lead_time_h: a.lead_time_h, timestamp: a.timestamp }))
          const id = run.dataset_id
          return (
            <>
              <Card title="Download">
                <div className="row">
                  <a className="btn btn--primary" href={reportHref(id, 'html')} target="_blank" rel="noreferrer">Open report</a>
                  <a className="btn" href={reportHref(id, 'html', true)}>Download HTML</a>
                  <button className="btn" type="button" onClick={() => frame.current?.contentWindow?.print()}>Print or save as PDF</button>
                  <a className="btn" href={reportHref(id, 'csv')}>Time series (CSV)</a>
                  <a className="btn" href={reportHref(id, 'json')}>Everything (JSON)</a>
                </div>
                <p className="muted" style={{ marginTop: 10 }}>
                  The HTML report needs nothing else to open: charts are inline and nothing is loaded from the internet. Use Print to save it as a PDF.
                  The CSV has every sample with the Health Index, residual and alert flags; the JSON adds the asset, analysis, outlook and data-quality report.
                </p>
              </Card>
              <Card title="Key figures">
                <dl className="kv">
                  <dt>Dataset</dt><dd>{run.name}</dd>
                  <dt>Mode</dt><dd>{run.mode}</dd>
                  <dt>Health Index (end of data)</dt><dd>{fmt(run.analysis.health.score, 0)} · {run.analysis.health.band}</dd>
                  <dt>Alerts</dt><dd>{run.analysis.alerts.length}</dd>
                  <dt>Recommendations</dt><dd>{run.analysis.recommendations.length}</dd>
                </dl>
              </Card>
              <Card title="Lead time against plain thresholds">
                {leadRows.length ? (
                  <DataTable table={{ columns: ['type', 'module', 'detector', 'origin', 'lead_time_h', 'timestamp'], rows: leadRows }} />
                ) : (
                  <p className="muted">No lead time recorded for this dataset. It is computed for the generated scenarios only, where the injected fault time is known (see the self-test report).</p>
                )}
              </Card>
              <Card title="Preview">
                <iframe ref={frame} title="Report preview" src={reportHref(id, 'html')} style={{ width: '100%', height: 900, border: '1px solid var(--border-strong)', borderRadius: 10, background: '#fff' }} />
              </Card>
            </>
          )
        }}
      </Gate>
    </>
  )
}
