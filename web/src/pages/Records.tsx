import { Gate } from '../components/Gate'
import { Card, DataTable, Note, PageTitle } from '../components/ui'

export default function Records() {
  return (
    <>
      <PageTitle title="Records" sub="Per-record twin view for data without timestamps, worst Health Index first." />
      <Gate timeSeries={false}>
        {(run) =>
          run.mode !== 'snapshot' || !run.records ? (
            <Note tone="info">This dataset has a time axis, so it is shown on the time-series pages. Records mode is only for files without timestamps.</Note>
          ) : (
            <Card title={`${run.records.rows.length} records`}>
              <DataTable table={run.records} format={(_c, v) => (typeof v === 'string' && v.length > 36 ? <span title={v}>{v.slice(0, 34)}…</span> : undefined)} />
              <p className="muted" style={{ marginTop: 8 }}>Steady-state estimate: thermal lag is ignored because there is no time axis.</p>
            </Card>
          )
        }
      </Gate>
    </>
  )
}
