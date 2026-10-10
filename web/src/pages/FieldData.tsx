import { useMemo } from 'react'
import { useRun } from '../api/client'
import { TimeChart } from '../charts/TimeChart'
import { Card, Note, PageTitle, Skeleton } from '../components/ui'
import { AlertItem } from '../components/ui'
import { CountsTable } from './DataHealth'

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)

export default function FieldData() {
  const q = useRun('kaggle')
  const run = q.data
  const range = useMemo<[number, number] | null>(() => (run?.start && run.end ? [Date.parse(run.start), Date.parse(run.end)] : null), [run])

  const sensor = useMemo(() => (run ? run.analysis.alerts.filter((a) => a.origin === 'sensor') : []), [run])
  const byType = useMemo(() => {
    const m = new Map<string, number>()
    sensor.forEach((a) => m.set(a.type, (m.get(a.type) ?? 0) + 1))
    return [...m.entries()].sort((a, b) => b[1] - a[1])
  }, [sensor])

  return (
    <>
      <PageTitle title="Real Field Data" sub="A different transformer, real measurements: what the twin does with sensors it cannot trust." />
      <Note tone="warn">
        <strong>Different transformer (about 155 kVA, rating estimated from the data). Real measurements.</strong> Its findings say something about data
        quality, not about Transformer-1. This dataset has no leak or theft events, so none are claimed.
      </Note>
      {q.isError && <Note tone="error">{q.error.message}</Note>}
      {q.isLoading && <Skeleton h={300} />}
      {run && (
        <>
          <div className="grid grid--2">
            <Card title="Is the oil-temperature sensor believable?">
              {(() => {
                const verdict = isObj(run.health_report.plausibility) && isObj(run.health_report.plausibility.verdict) ? run.health_report.plausibility.verdict : {}
                const frac = isObj(run.summary.plausibility) ? Number(run.summary.plausibility.implausible_fraction) : NaN
                return (
                  <>
                    <ul className="caps" style={{ gridTemplateColumns: '1fr' }}>
                      {Object.entries(verdict).map(([ch, v]) => (
                        <li key={ch}><strong>{ch}</strong>: {String(v)}</li>
                      ))}
                    </ul>
                    {verdict.OTI_C === 'suspect' && (
                      <p style={{ marginTop: 8 }}>
                        Our twin&apos;s physics says this oil-temperature sensor can&apos;t be reading top-oil{Number.isFinite(frac) ? ` (${Math.round(frac * 100)} % of rows are below what any oil-filled unit can show)` : ''}.
                        Check its placement. A pure ML model would happily have learned from it.
                      </p>
                    )}
                  </>
                )
              })()}
            </Card>
            <Card title="Data-quality flags"><CountsTable counts={isObj(run.health_report.flag_counts_final) ? run.health_report.flag_counts_final : isObj(run.health_report.flag_counts) ? run.health_report.flag_counts : {}} /></Card>
          </div>

          <div className="grid grid--2">
            <Card title="Oil temperature vs ambient">
              <TimeChart range={range} cursor={null} clip={false} yTitle="°C" traces={[
                { name: 'Top oil (OTI)', series: run.series.OTI_C, color: '#0b0b0c', width: 1 },
                { name: 'Ambient (ATI)', series: run.series.ATI_C ?? run.series.amb_C, color: '#8a8d93', width: 1 },
              ]} />
              <p className="muted">Plateaus at 245–250 °C are sensor glitches, not heat.</p>
            </Card>
            <Card title="Oil level gauge">
              <TimeChart range={range} cursor={null} clip={false} yTitle="%" traces={[{ name: 'OLI', series: run.series.OLI_pct, color: '#0b0b0c', width: 1 }]} />
              <p className="muted">Drifts from about 40 % to 100 % with no refill step: oil cannot rise like that, so the gauge is faulty.</p>
            </Card>
          </div>

          <Card title={`Sensor-origin alerts (${sensor.length}): check the device, not the transformer`}>
            <ul className="row" style={{ listStyle: 'none', padding: 0, margin: '0 0 12px' }}>
              {byType.map(([t, n]) => <li key={t} className="chip chip--sensor">{t.replace(/_/g, ' ')} · {n}</li>)}
            </ul>
            <ul className="alerts">
              {sensor.slice(0, 25).map((a) => <AlertItem key={a.id} alert={a} />)}
            </ul>
            {sensor.length > 25 && <p className="muted">Showing 25 of {sensor.length}. All of them are in Alerts & Maintenance when this dataset is selected.</p>}
          </Card>
        </>
      )}
    </>
  )
}
