import { useSelfTest } from '../api/client'
import { Card, DataTable, Note, PageTitle, Skeleton } from '../components/ui'

const LABEL: Record<string, string> = { measurement: 'Measurement accuracy', trip: 'Trip tests', oil: 'Oil channel', status: 'Status message' }

export default function SelfTest() {
  const q = useSelfTest()
  const sections = new Map<string, NonNullable<typeof q.data>['rows']>()
  q.data?.rows.forEach((r) => {
    const k = String(r.section)
    sections.set(k, [...(sections.get(k) ?? []), r])
  })
  return (
    <>
      <PageTitle title="Self-Test" sub="CPRI's acceptance-test format: reference value vs software value, pass at 1 % or better." />
      <Note tone="warn"><strong>Bench settings, not operating alarms.</strong> The 50 A and 60 °C trip values are lab-rig setpoints from the organizers&apos; sheet. Operating alarms use the thresholds in the analytics.</Note>
      {q.isLoading && <Skeleton h={240} />}
      {q.isError && <Note tone="error">{q.error.message}</Note>}
      {q.data && [...sections.entries()].map(([section, rows]) => (
        <Card key={section} title={LABEL[section] ?? section}>
          <DataTable
            table={{ columns: q.data!.columns.filter((c) => c !== 'section'), rows }}
            format={(col, v) =>
              col === 'pass' ? (v === true ? <span className="pass">✓ Pass</span> : v === false ? <span className="fail">✕ Fail</span> : '—') : undefined
            }
          />
        </Card>
      ))}
      <Card title="Status message to master number">
        <button className="btn" type="button" disabled>Send test message</button>
        <p className="muted" style={{ marginTop: 8 }}>Coming soon: the Telegram channel is not connected to the backend yet.</p>
      </Card>
    </>
  )
}
