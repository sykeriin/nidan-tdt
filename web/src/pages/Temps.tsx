import { TimeChart, type TraceSpec } from '../charts/TimeChart'
import { Gate } from '../components/Gate'
import { Card, Note, PageTitle, Unavailable } from '../components/ui'
import { useSession } from '../context/Session'
import { fmt } from '../lib/series'

const MEASURED = '#0b0b0c'
const TWIN = '#8a8d93'

export default function Temps() {
  const s = useSession()
  const range: [number, number] | null = s.bounds ? [s.bounds.start, s.bounds.end] : null
  return (
    <>
      <PageTitle title="Loading & Temperatures" sub="Solid black is what the sensors measure, grey is what the twin predicts, and the gap between them is what the analytics watch." />
      <Gate>
        {(run, now) => {
          if (!now) return null
          const c = run.capabilities
          const measured = run.mode === 'full'
          const alerts = now.raised.filter((a) => a.origin === 'asset')
          const chart = (traces: TraceSpec[], yTitle: string, hlines?: { y: number; label: string }[]) => (
            <TimeChart traces={traces} range={range} cursor={now.ms} yTitle={yTitle} hlines={hlines} alerts={alerts} height={240} />
          )
          const drifting = c.residual_fidelity && now.at('fidelity_rmse_C') != null && run.summary.drift_message && (now.at('fidelity_alert') ?? 0) > 0
          return (
            <div className="grid grid--2">
              <Card title="Loading">
                {chart(
                  [{ name: 'Loading', series: run.series.loading_pct, color: '#0b0b0c' }],
                  '% of rated',
                  [{ y: 90, label: 'warning 90 %' }, { y: 100, label: 'alarm 100 %' }],
                )}
              </Card>
              <Card title="Phase currents R / Y / B">
                {chart(
                  [
                    { name: 'R', series: run.series.IR, color: '#0b0b0c', width: 1.2 },
                    { name: 'Y', series: run.series.IY, color: '#55595f', width: 1.2 },
                    { name: 'B', series: run.series.IB, color: '#a9acb1', width: 1.2 },
                  ],
                  'A',
                )}
                {!c.unbalance && <Unavailable>per-phase currents were derived from a total, so unbalance is not shown.</Unavailable>}
              </Card>
              <Card title="Phase voltages R / Y / B">
                {c.voltage_quality ? (
                  chart(
                    [
                      { name: 'R', series: run.series.VR, color: '#0b0b0c', width: 1.2 },
                      { name: 'Y', series: run.series.VY, color: '#55595f', width: 1.2 },
                      { name: 'B', series: run.series.VB, color: '#a9acb1', width: 1.2 },
                    ],
                    'V',
                  )
                ) : (
                  <Unavailable>this dataset has no phase voltages.</Unavailable>
                )}
              </Card>
              <Card title={measured ? 'Top oil: measured vs twin' : 'Top oil: estimated by twin'}>
                {chart(
                  [
                    { name: 'Twin', series: run.series.twin_oil_C, color: TWIN, dash: 'dash' },
                    ...(measured ? [{ name: 'Measured', series: run.series.OTI_C, color: MEASURED, fillPrev: true }] : []),
                  ],
                  '°C',
                )}
              </Card>
              <Card title="Hot spot">
                {chart(
                  [
                    { name: 'Twin', series: run.series.twin_hs_C, color: TWIN, dash: 'dash' },
                    ...(measured && run.series.WTI_C ? [{ name: 'Measured (WTI)', series: run.series.WTI_C, color: MEASURED }] : []),
                  ],
                  '°C',
                  [{ y: 98, label: 'ageing rate 1 at 98 °C' }],
                )}
                {!(measured && run.series.WTI_C) && <p className="muted">No winding sensor: hot spot is estimated by the twin.</p>}
              </Card>
              <Card title="Ambient">
                {chart([{ name: 'Ambient', series: run.series.amb_C, color: '#8a8d93' }], '°C')}
              </Card>
              <Card title="Residual (measured − twin)">
                {c.residual_fidelity ? (
                  chart([{ name: 'Residual', series: run.series.residual_oil_C, color: MEASURED }], 'K')
                ) : (
                  <Unavailable>the residual needs a measured oil temperature and a running twin.</Unavailable>
                )}
              </Card>
              <Card title="Twin fidelity (rolling 24 h RMSE)">
                {c.residual_fidelity ? (
                  <>
                    {chart([{ name: 'RMSE', series: run.series.fidelity_rmse_C, color: TWIN }], 'K')}
                    <p className="muted">Now {fmt(now.at('fidelity_rmse_C'))} K</p>
                    {drifting && <Note tone="warn">{String(run.summary.drift_message)}</Note>}
                  </>
                ) : (
                  <Unavailable>fidelity compares the twin with a measured oil temperature.</Unavailable>
                )}
              </Card>
            </div>
          )
        }}
      </Gate>
    </>
  )
}
