import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { Run } from '../api/client'
import { useBrief, useOutlook } from '../api/client'
import { GapChart, type GapWindow } from '../charts/GapChart'
import { Gate } from '../components/Gate'
import { Twin3D } from '../components/Twin3D'
import { AlertItem, Card, PageTitle, StatusChip, SubScoreBars, Unavailable } from '../components/ui'
import { DiagnosisBars, HealthDial, Instrument, RulFan, WorkOrder, useTween } from '../components/viz'
import { useSession } from '../context/Session'
import type { Band, Now } from '../lib/derive'
import { fmt, slice } from '../lib/series'
import { buildTwinView } from '../lib/twinView'

const HOUR = 3600_000

function Hero({ run, now }: { run: Run; now: Now }) {
  const s = useSession()
  const brief = useBrief(s.datasetId, now.ms)
  const b = brief.data
  const measured = run.mode === 'full'
  const resid = measured ? now.at('residual_oil_C') : null
  const gap = useTween(resid)
  const level = b?.level ?? 'nodata'
  const label = { good: 'All clear', watch: 'Watch', critical: 'Needs attention', nodata: 'No data' }[level]
  return (
    <section className="hero" data-level={level} aria-live="polite">
      <div>
        <div className="hero__meta"><span className="pulse" aria-hidden /><strong>{label}</strong></div>
        <p className={`hero__sentence ${b ? '' : 'hero__sentence--loading'}`}>{b ? b.sentence : 'Reading the transformer…'}</p>
      </div>
      <div className="gap-meter">
        <div className="gap-meter__label">{measured ? 'Gap, measured minus twin' : 'Oil temperature (twin estimate)'}</div>
        <div className="gap-meter__value">
          {measured ? (gap == null ? '—' : `${gap >= 0 ? '+' : ''}${gap.toFixed(1)}`) : fmt(now.at('twin_oil_C'), 0)}
          <small>{measured ? 'K' : '°C'}</small>
        </div>
        <div className="gap-meter__sub">{measured ? (b?.kpis.residual_pct != null ? `${b.kpis.residual_pct >= 0 ? '+' : ''}${b.kpis.residual_pct} % of the twin's rise` : 'Twin and sensor agree') : 'No oil sensor to compare with'}</div>
      </div>
    </section>
  )
}

const stateOf = (v: number | null | undefined, warn: number, crit: number): 'ok' | 'watch' | 'critical' => (v == null ? 'ok' : v >= crit ? 'critical' : v >= warn ? 'watch' : 'ok')

function Instruments({ run, now }: { run: Run; now: Now }) {
  const s = useSession()
  const brief = useBrief(s.datasetId, now.ms)
  const k = brief.data?.kpis
  const measured = run.mode === 'full'
  const from = now.ms - 48 * HOUR
  const spark = (col: string) => slice(run.series[col], from, now.ms).v
  const hasWti = measured && now.at('WTI_C') != null
  const hs = hasWti ? now.at('WTI_C') : now.at('twin_hs_C')
  const oil = measured ? now.at('OTI_C') : now.at('twin_oil_C')
  const load = now.at('loading_pct')
  const rate = k?.ageing_rate ?? now.at('aging_rate_actual') ?? now.at('aging_rate')
  const life = (run.summary.life_consumed_days ?? {}) as { expected?: number; actual?: number }
  const caps = run.capabilities
  const ttl = k?.time_to_limit
  const head = k?.headroom
  return (
    <div className="insts">
      <Instrument name={`Hot spot ${hasWti ? '(measured)' : '(twin estimate)'}`} value={fmt(hs, 0)} unit="°C" tone="twin"
        state={stateOf(hs, 98, 120)} spark={spark(hasWti ? 'WTI_C' : 'twin_hs_C')}
        sub={<>Ageing reference <strong>98 °C</strong>, limit <strong>120 °C</strong></>} />
      <Instrument name="Top oil" value={fmt(oil, 0)} unit="°C" tone={measured ? 'measured' : 'twin'} state={stateOf(oil, 85, 95)} spark={spark(measured ? 'OTI_C' : 'twin_oil_C')}
        sub={measured ? <>Twin says <strong>{fmt(now.at('twin_oil_C'), 0)} °C</strong></> : 'Estimated from load and ambient'} />
      <Instrument name="Load" value={fmt(load, 0)} unit="% of rating" state={stateOf(load, 90, 100)} spark={spark('loading_pct')}
        sub={caps.unbalance ? <>Phase unbalance <strong>{fmt(k?.unbalance_pct, 0)} %</strong></> : 'Per-phase currents not available'} />
      <Instrument name="Ageing speed" value={fmt(rate, 2)} unit="× design" state={stateOf(rate, 1.5, 5)}
        spark={spark(measured && run.series.aging_rate_actual ? 'aging_rate_actual' : 'aging_rate')}
        sub={caps.ageing_rul ? <>Life used this period <strong>{fmt(measured ? life.actual : life.expected, 1)} days</strong></> : 'Needs load and ambient over time'} />
      <Instrument name="Spare capacity" value={head ? fmt(head.pu * 100, 0) : '—'} unit="% of rating" tone="twin"
        state={head && load != null && load > head.pu * 100 ? 'critical' : 'ok'}
        sub={head ? <>Largest steady load within limits at {fmt(head.ambient_C, 0)} °C, set by the <strong>{head.limiting ?? 'limits'}</strong></> : 'Needs load and ambient'} />
      <Instrument name="Time to a limit" value={!ttl ? '—' : ttl.status === 'reaches_limit' ? fmt(ttl.hours, 1) : ttl.status === 'already_reached' ? '0' : 'Not'}
        unit={!ttl ? undefined : ttl.status === 'not_reached' ? 'reached' : 'hours'}
        state={ttl?.status === 'already_reached' ? 'critical' : ttl?.status === 'reaches_limit' && (ttl.hours ?? 99) < 6 ? 'watch' : 'ok'}
        sub={ttl ? (ttl.status === 'not_reached' ? <>Oil settles near <strong>{fmt(ttl.steady_state_oil_C, 0)} °C</strong> at this load</> : <>At the present load, until the oil reaches <strong>{fmt(ttl.target_oil_C, 0)} °C</strong></>) : 'Needs load and ambient'} />
    </div>
  )
}

function OverviewBody({ run, now }: { run: Run; now: Now }) {
  const s = useSession()
  const [win, setWin] = useState<GapWindow>('7d')
  const view = useMemo(() => buildTwinView(run, now, run.name, s.simulated), [run, now, s.simulated])
  const brief = useBrief(s.datasetId, now.ms)
  const outlook = useOutlook(s.datasetId, now.ms, !s.playing)
  const caps = run.capabilities
  const latest = [...now.active].reverse().slice(0, 4)
  const health = now.health
  const bounds = s.bounds!
  const rul = outlook.data?.rul
  const risk = outlook.data?.trip_risk_30d

  return (
    <>
      <Hero run={run} now={now} />

      <div className="overview">
        <Card className="card--hero">
          <Twin3D view={view} height={560} />
        </Card>
        <div className="stack">
          <Card title="Health" aside={health.band && <StatusChip band={health.band as Band} />}>
            <HealthDial score={health.score} band={health.band} capped={health.capped} />
            <SubScoreBars components={health.components} weights={health.weights} />
          </Card>
          <Card title="What the evidence points to">
            <DiagnosisBars diagnosis={brief.data?.diagnosis ?? []} />
          </Card>
        </div>
      </div>

      <Card
        title="The gap between physics and data"
        aside={(
          <div className="tabs" role="tablist" aria-label="Chart window" style={{ border: 0 }}>
            {(['2d', '7d', 'all'] as GapWindow[]).map((w) => (
              <button key={w} role="tab" aria-selected={win === w} onClick={() => setWin(w)}>{w === 'all' ? 'Whole run' : `${w.replace('d', '')} days`}</button>
            ))}
          </div>
        )}
      >
        <GapChart run={run} cursor={now.ms} bounds={bounds} alerts={s.alerts} forecast={s.playing ? undefined : outlook.data?.forecast} window={win} />
        <p className="muted" style={{ marginTop: 6 }}>
          {run.mode === 'full'
            ? 'The black line is the oil-temperature sensor, the grey line is what the physics predicts for the same load and weather, and the hatched band is the gap the analytics watch.'
            : 'No oil sensor: the grey line is the twin\'s estimate from load and ambient temperature.'}
          {outlook.data?.forecast.available && !s.playing ? ` The dashed grey line continues the twin 24 hours ahead (band: ${outlook.data.forecast.band_basis}).` : ''}
        </p>
      </Card>

      <Instruments run={run} now={now} />

      <div className="grid grid--3">
        <Card className="card--ink" title="Maintenance work order"><WorkOrder advice={brief.data?.advice ?? null} /></Card>
        <Card title="Active alerts" aside={<Link to="/alerts">All alerts</Link>}>
          {latest.length ? (
            <ul className="alerts">{latest.map((a) => <AlertItem key={a.id} alert={a} onClick={() => s.setCursor(Date.parse(a.timestamp))} />)}</ul>
          ) : <p className="muted">No alerts in the last 24 h of the replay.</p>}
        </Card>
        <Card title="Remaining insulation life">
          {!caps.ageing_rul ? <Unavailable>ageing needs load and ambient temperature over time.</Unavailable> : rul ? (
            <>
              <RulFan rul={rul} />
              {risk && (
                <p className="muted" style={{ marginTop: 8 }}>
                  Chance of reaching a temperature limit in the next 30 days: <strong style={{ color: 'var(--text)' }}>{(risk.probability * 100).toFixed(risk.probability > 0 && risk.probability < 0.1 ? 1 : 0)} %</strong> ({risk.runs} simulated months).
                </p>
              )}
              <p className="muted" style={{ marginTop: 6 }}>{rul.note}</p>
            </>
          ) : <p className="muted">{s.playing ? 'Paused while replaying; the projection updates when you stop.' : 'Running 500 simulations…'}</p>}
        </Card>
      </div>
    </>
  )
}

export default function Overview() {
  return (
    <>
      <PageTitle title="Overview" />
      <Gate>{(run, now) => (now ? <OverviewBody run={run} now={now} /> : null)}</Gate>
    </>
  )
}
