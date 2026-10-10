import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import type { Alert, Run } from '../api/client'
import { TimeChart, type TraceSpec } from '../charts/TimeChart'
import { Gate } from '../components/Gate'
import { Twin3D } from '../components/Twin3D'
import { AlertItem, Card, HealthGauge, PageTitle, StatusChip, SubScoreBars, Unavailable } from '../components/ui'
import { useSession } from '../context/Session'
import type { Band, Now } from '../lib/derive'
import { fmt } from '../lib/series'
import { buildTwinView } from '../lib/twinView'

const MODULES: [string, string, string][] = [
  ['overloading', 'Overloading', 'thermal_twin'],
  ['insulation', 'Insulation', 'ageing_rul'],
  ['short_circuit', 'Short circuit', 'through_fault'],
  ['oil', 'Oil level', 'oil_leak_theft'],
]

/** Worst asset-origin severity among active alerts of a module; sensor alerts never colour a module. */
function moduleBand(active: Alert[], module: string): Band {
  const mine = active.filter((a) => a.module === module && a.origin === 'asset')
  if (mine.some((a) => a.severity === 'critical')) return 'red'
  if (mine.some((a) => a.severity === 'warning')) return 'yellow'
  return 'green'
}

const unbalancePct = (now: Now): number | null => {
  const i = ['IR', 'IY', 'IB'].map(now.at)
  if (i.some((x) => x == null)) return null
  const v = i as number[]
  const mean = v.reduce((a, b) => a + b, 0) / 3
  return mean ? (Math.max(...v.map((x) => Math.abs(x - mean))) / mean) * 100 : null
}

function OverviewBody({ run, now }: { run: Run; now: Now }) {
  const s = useSession()
  const view = useMemo(() => buildTwinView(run, now, run.name, s.simulated), [run, now, s.simulated])
  const caps = run.capabilities
  const measured = run.mode === 'full'
  const rated = Number(run.asset.i_rated_A) || null
  const life = (run.summary.life_consumed_days ?? {}) as { expected?: number; actual?: number }
  const rul = run.analysis.rul
  const range: [number, number] | null = s.bounds ? [s.bounds.start, s.bounds.end] : null
  const latest = [...now.active].reverse().slice(0, 5)

  const traces: TraceSpec[] = [
    { name: 'Twin (predicted)', series: run.series.twin_oil_C, color: '#0284C7', dash: 'dash' },
    ...(measured ? [{ name: 'Measured', series: run.series.OTI_C, color: '#0F172A', fillPrev: true }] : []),
  ]
  const unb = caps.unbalance ? unbalancePct(now) : null

  return (
    <>
      <div className="overview">
        <div className="stack">
          <Card title="Transformer-1, live 3D twin">
            <Twin3D view={view} />
            <p className="muted" style={{ marginTop: 8 }}>
              Representative 3D model (power-transformer style). Hover a part for its status, click for readings and the
              recommended test. Parts turn yellow or red from the analytics; sensor faults get a badge instead.
            </p>
          </Card>
          <Card title={measured ? 'Top-oil temperature: measured vs twin' : 'Top-oil temperature: estimated by the twin'}>
            {!measured && <p className="muted">Running on meter data only: temperatures are estimated from load and ambient.</p>}
            <TimeChart traces={traces} range={range} cursor={now.ms} yTitle="°C" alerts={now.raised.filter((a) => a.origin === 'asset')} />
          </Card>
        </div>

        <div className="stack">
          <Card title="Health Index" aside={now.health.band && <StatusChip band={now.health.band} />}>
            <HealthGauge score={now.health.score} band={now.health.band} capped={now.health.capped} />
            <SubScoreBars components={now.health.components} weights={now.health.weights} />
            <p className="muted" style={{ marginTop: 8 }}>A transparent engineering score, not a trained one. Weights renormalise over the sub-scores this dataset can support.</p>
          </Card>

          <Card title="Remaining life">
            {caps.ageing_rul ? (
              <>
                <div className="big">{String(run.summary.rul_display ?? '—')}</div>
                <dl className="kv" style={{ marginTop: 8 }}>
                  <dt>Risk class</dt><dd>{rul?.risk ?? '—'}</dd>
                  <dt>Ageing rate now</dt><dd>{fmt(now.at('aging_rate_actual') ?? now.at('aging_rate'), 2)} × normal</dd>
                  <dt>Life used, expected</dt><dd>{fmt(life.expected, 2)} days</dd>
                  <dt>Life used, actual</dt><dd>{measured ? `${fmt(life.actual, 2)} days` : '—'}</dd>
                </dl>
              </>
            ) : (
              <Unavailable>ageing needs current and ambient temperature over time.</Unavailable>
            )}
          </Card>

          <Card title="Active alerts" aside={<Link to="/alerts">All alerts</Link>}>
            {latest.length ? (
              <ul className="alerts">
                {latest.map((a) => <AlertItem key={a.id} alert={a} onClick={() => s.setCursor(Date.parse(a.timestamp))} />)}
              </ul>
            ) : (
              <p className="muted">No alerts in the last 24 h of the replay.</p>
            )}
          </Card>
        </div>
      </div>

      <div className="grid grid--4">
        <Card title="Top oil">
          <div className="big">{fmt(measured ? now.at('OTI_C') : now.at('twin_oil_C'))} °C</div>
          <dl className="kv" style={{ marginTop: 8 }}>
            <dt>{measured ? 'Twin' : 'Source'}</dt><dd>{measured ? `${fmt(now.at('twin_oil_C'))} °C` : 'estimated by twin'}</dd>
            <dt>Residual</dt><dd>{measured && caps.residual_fidelity ? `${fmt(now.at('residual_oil_C'))} K` : '—'}</dd>
            <dt>Hot spot {measured && now.at('WTI_C') != null ? '(measured)' : '(twin)'}</dt>
            <dd>{fmt(measured && now.at('WTI_C') != null ? now.at('WTI_C') : now.at('twin_hs_C'))} °C</dd>
            <dt>Fidelity RMSE</dt><dd>{caps.residual_fidelity ? `${fmt(now.at('fidelity_rmse_C'))} K` : '—'}</dd>
          </dl>
          {!caps.residual_fidelity && <p className="muted" style={{ marginTop: 6 }}>Residual and fidelity need a measured oil temperature.</p>}
        </Card>

        <Card title="Loading">
          <div className="big">{fmt(now.at('loading_pct'), 0)} %</div>
          <dl className="kv" style={{ marginTop: 8 }}>
            <dt>Load</dt><dd>{fmt(now.at('load_pu'), 2)} pu</dd>
            {(['IR', 'IY', 'IB'] as const).map((c, i) => (
              <Frag key={c} label={`Phase ${'RYB'[i]}`} value={`${fmt(now.at(c), 0)} A${rated ? ` · ${fmt(((now.at(c) ?? NaN) / rated) * 100, 0)} %` : ''}${caps.voltage_quality ? ` · ${fmt(now.at(`V${'RYB'[i]}`), 0)} V` : ''}`} />
            ))}
            <dt>Current unbalance</dt><dd>{caps.unbalance ? `${fmt(unb)} %` : '—'}</dd>
            <dt>Power factor</dt><dd>{fmt(now.at('PF'), 2)}</dd>
          </dl>
        </Card>

        <Card title="Failure modules">
          <ul className="caps" style={{ gridTemplateColumns: '1fr' }}>
            {MODULES.map(([key, label, cap]) => (
              <li key={key} style={{ justifyContent: 'space-between' }}>
                {label}
                {caps[cap] ? <StatusChip band={moduleBand(now.active, key)} /> : <StatusChip band="grey" text="No data" />}
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Report">
          <p className="muted">Summary of this run with a Data Health appendix.</p>
          <p style={{ marginTop: 8 }}>
            <Link className="btn" to="/reports">Open reports</Link>
          </p>
        </Card>
      </div>

      <Card title="Recommended maintenance">
        {run.analysis.recommendations.length ? (
          <ul className="alerts">
            {run.analysis.recommendations
              .filter((r) => now.raised.some((a) => a.id === r.alert_id))
              .slice(-4)
              .reverse()
              .map((r) => (
                <li className="alert" key={r.id}>
                  <div className="alert__btn" style={{ cursor: 'default' }}>
                    <span className="alert__top"><strong>{r.action}</strong><span className="chip chip--mode">{r.urgency}</span></span>
                    {r.test && <span>Test: {r.test}</span>}
                    {r.standard_ref && <span className="muted">Ref: {r.standard_ref}</span>}
                  </div>
                </li>
              ))}
          </ul>
        ) : (
          <p className="muted">No maintenance actions recommended for this run.</p>
        )}
      </Card>
    </>
  )
}

function Frag({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  )
}

export default function Overview() {
  return (
    <>
      <PageTitle title="Overview" sub="Physics says what should happen, data says what is happening, the AI watches the gap." />
      <Gate>{(run, now) => (now ? <OverviewBody run={run} now={now} /> : null)}</Gate>
    </>
  )
}
