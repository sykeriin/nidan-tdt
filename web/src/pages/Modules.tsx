import { useState } from 'react'
import type { Alert, Run } from '../api/client'
import { TimeChart } from '../charts/TimeChart'
import { Gate } from '../components/Gate'
import { AlertItem, Card, DataTable, PageTitle, Unavailable } from '../components/ui'
import { useSession } from '../context/Session'
import type { Now } from '../lib/derive'
import { fmt } from '../lib/series'

const TABS = [
  ['overloading', 'Overloading'],
  ['insulation', 'Insulation'],
  ['short_circuit', 'Short circuit'],
  ['oil', 'Oil leak / theft'],
  ['unbalance', 'Unbalance'],
  ['moisture', 'Moisture exposure'],
] as const

function Alerts({ list, onJump }: { list: Alert[]; onJump: (ms: number) => void }) {
  if (!list.length) return <p className="muted">No alerts from this module up to the replay time.</p>
  return (
    <ul className="alerts">
      {[...list].reverse().slice(0, 8).map((a) => <AlertItem key={a.id} alert={a} onClick={() => onJump(Date.parse(a.timestamp))} />)}
    </ul>
  )
}

function Body({ run, now, tab }: { run: Run; now: Now; tab: (typeof TABS)[number][0] }) {
  const s = useSession()
  const c = run.capabilities
  const range: [number, number] | null = s.bounds ? [s.bounds.start, s.bounds.end] : null
  const asset = now.raised.filter((a) => a.origin === 'asset')
  const chart = (traces: Parameters<typeof TimeChart>[0]['traces'], yTitle: string, hlines?: { y: number; label: string }[]) => (
    <TimeChart traces={traces} range={range} cursor={now.ms} yTitle={yTitle} hlines={hlines} alerts={asset} height={240} />
  )
  const of = (m: string) => now.raised.filter((a) => a.module === m)

  if (tab === 'overloading') {
    return (
      <div className="grid grid--2">
        <Card title="Loading and hot spot">
          {chart([{ name: 'Loading %', series: run.series.loading_pct, color: '#0b0b0c' }], '% of rated', [{ y: 100, label: 'alarm' }])}
          {chart([{ name: 'Hot spot (twin)', series: run.series.twin_hs_C, color: '#8a8d93', dash: 'dash' }, ...(run.series.WTI_C ? [{ name: 'Hot spot (measured)', series: run.series.WTI_C, color: '#0b0b0c' }] : [])], '°C', [{ y: 98, label: '98 °C' }])}
          <p className="muted">Loading %, hot spot against limits, and the ageing rate it causes.</p>
        </Card>
        <Card title="Alerts"><Alerts list={of('overloading')} onJump={s.setCursor} /></Card>
      </div>
    )
  }
  if (tab === 'insulation') {
    return (
      <div className="grid grid--2">
        <Card title="Ageing rate">
          {c.ageing_rul ? (
            chart([
              { name: 'Expected (twin)', series: run.series.aging_rate, color: '#8a8d93', dash: 'dash' },
              ...(run.series.aging_rate_actual ? [{ name: 'Actual (measured oil)', series: run.series.aging_rate_actual, color: '#0b0b0c' }] : []),
            ], '× normal', [{ y: 1, label: 'normal ageing' }])
          ) : <Unavailable>ageing needs current and ambient temperature over time.</Unavailable>}
          <p className="muted">
            {String(run.summary.rul_display ?? '')}. Thermal ageing only: no moisture, partial discharge or dissolved gas analysis, and no breakdown-date claims.
          </p>
        </Card>
        <Card title="Alerts"><Alerts list={of('insulation')} onJump={s.setCursor} /></Card>
      </div>
    )
  }
  if (tab === 'short_circuit') {
    const ev = run.events
    if (!c.through_fault || !ev.rows.length) {
      return <Card><Unavailable>through-fault stress needs an event log; 15-minute averages cannot show a short circuit.</Unavailable><Alerts list={of('short_circuit')} onJump={s.setCursor} /></Card>
    }
    const upto = ev.rows.filter((r) => Date.parse(String(r.timestamp)) <= now.ms)
    let cum = 0
    const rows = upto.map((r) => ({ ...r, cumulative_i2t: (cum += Number(r.i2t_pu2s) || 0) }))
    return (
      <div className="stack">
        <Card title="Through-fault log (cumulative I²t)">
          {rows.length ? <DataTable table={{ columns: ['timestamp', 'phase', 'peak_pu', 'duration_ms', 'i2t_pu2s', 'cumulative_i2t'], rows }} format={(col, v) => (col === 'timestamp' ? new Date(String(v)).toLocaleString('en-GB', { timeZone: 'Asia/Kolkata' }) : undefined)} /> : <p className="muted">No through-faults up to the replay time.</p>}
          <p className="muted" style={{ marginTop: 8 }}>Moderate ≥ 3 pu, severe ≥ 8 pu (assumed). Stress rule: 1 severe or 3 moderate since reset.</p>
        </Card>
        <Card title="Alerts"><Alerts list={of('short_circuit')} onJump={s.setCursor} /></Card>
      </div>
    )
  }
  if (tab === 'oil') {
    return (
      <div className="grid grid--2">
        <Card title="Oil level">
          {c.oil_leak_theft ? chart([{ name: 'Oil level %', series: run.series.OLI_pct, color: '#0b0b0c' }], '%', [{ y: 85, label: 'low-level limit 85 %' }]) : <Unavailable>this dataset has no oil level channel.</Unavailable>}
          <p className="muted">A slow slope is a leak. A step within an hour with no thermal cause, especially at night, is possible theft or tampering.</p>
        </Card>
        <Card title="Alerts"><Alerts list={of('oil')} onJump={s.setCursor} /></Card>
      </div>
    )
  }
  if (tab === 'unbalance') {
    const list = now.raised.filter((a) => a.module === 'electrical')
    return (
      <div className="grid grid--2">
        <Card title="Phase currents">
          {c.unbalance ? chart([
            { name: 'R', series: run.series.IR, color: '#0b0b0c', width: 1.2 },
            { name: 'Y', series: run.series.IY, color: '#55595f', width: 1.2 },
            { name: 'B', series: run.series.IB, color: '#a9acb1', width: 1.2 },
          ], 'A') : <Unavailable>unbalance needs measured R, Y and B currents.</Unavailable>}
          <p className="muted">
            Neutral: {c.neutral_measured ? `measured, ${fmt(now.at('IN'), 1)} A` : 'proxy from unbalance (no neutral sensor); no earthing claims'}.
          </p>
        </Card>
        <Card title="Alerts"><Alerts list={list} onJump={s.setCursor} /></Card>
      </div>
    )
  }
  return (
    <Card>
      <p className="tag-sim" style={{ display: 'inline-block' }}>EXPERIMENTAL</p>
      <p style={{ marginTop: 8 }}>
        The breathing-stress index (daily top-oil swing × humidity) is an uncalibrated heuristic for breathing-type units and has not been built yet.
        It is not validated and is not tied to any failure statistic.
      </p>
      {!c.breathing_index && <Unavailable>needs humidity and a daily temperature swing.</Unavailable>}
    </Card>
  )
}

export default function Modules() {
  const [tab, setTab] = useState<(typeof TABS)[number][0]>('overloading')
  return (
    <>
      <PageTitle title="Failure Modules" sub="Organised around CPRI's three failure causes: overloading, insulation, short circuit." />
      <div className="tabs" role="tablist">
        {TABS.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>{label}</button>
        ))}
      </div>
      <Gate>{(run, now) => (now ? <Body run={run} now={now} tab={tab} /> : null)}</Gate>
    </>
  )
}
