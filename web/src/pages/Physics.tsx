import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAgeingModels, useChain, useDetailed, useStepResponse, useWhatIf } from '../api/client'
import { TimeChart } from '../charts/TimeChart'
import { XYChart } from '../charts/XYChart'
import { Card, Note, PageTitle, Skeleton } from '../components/ui'
import { useProfile } from '../context/Profile'
import { useSession } from '../context/Session'
import { times } from '../lib/series'
import { useDebounced } from '../lib/useDebounced'

function Slider({ label, value, set, min, max, step, unit, digits = 2 }: {
  label: string; value: number; set: (v: number) => void; min: number; max: number; step: number; unit: string; digits?: number
}) {
  return (
    <label className="slider">
      <span>{label}</span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => set(Number(e.target.value))} />
      <output>{value.toFixed(digits)} {unit}</output>
    </label>
  )
}

const num = (v: unknown, d = 1) => (typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—')
/** Years past the display cap read as "> 40", like the rest of the dashboard (remaining life is a range, not a date). */
const years = (v: unknown) => (typeof v === 'number' && v > 40 ? '> 40' : num(v, 1))

function Chain() {
  const p = useProfile()
  const [load, setLoad] = useState(1.0)
  const [amb, setAmb] = useState(30)
  const chain = useChain(p.body, useDebounced(load, 250), useDebounced(amb, 250))
  const c = chain.data
  return (
    <Card title="1. From load to ageing: the calculation chain">
      <p className="muted" style={{ marginBottom: 12 }}>
        Six steps turn a load into insulation wear. The numbers are this transformer's own (change them on the <Link to="/profile">profile page</Link>).
      </p>
      <div style={{ display: 'grid', gap: 8, maxWidth: 640, marginBottom: 16 }}>
        <Slider label="Load" value={load} set={setLoad} min={0} max={1.6} step={0.05} unit="pu" />
        <Slider label="Ambient" value={amb} set={setAmb} min={0} max={50} step={1} unit="°C" digits={0} />
      </div>
      {chain.isError && <Note tone="error">{chain.error.message}</Note>}
      {!p.ready && <Note tone="info">Enter a rating on the profile page first.</Note>}
      {!c && p.ready && !chain.isError && <Skeleton h={180} />}
      {c && (
        <>
          <div className="chain">
            {c.steps.map((st, i) => (
              <div key={st.id} className="chain__step">
                <span className="chain__n">{i + 1}</span>
                <h3>{st.title}</h3>
                <span className="chain__formula">{st.formula}</span>
                <span className="chain__working">{st.working}</span>
                <span className="chain__value">{num(st.value, st.unit === '× normal' ? 2 : 1)} <span className="muted">{st.unit}</span></span>
                <span className="muted">{st.why}</span>
              </div>
            ))}
          </div>
          <p className="muted" style={{ marginTop: 12 }}>
            At this load the winding hot spot sits at <strong>{num(c.hot_spot_C)} °C</strong> and the insulation ages <strong>{num(c.ageing_rate, 2)}×</strong> as fast as designed
            {c.hours_per_equivalent_day != null && c.ageing_rate > 1 && <> (a day of life every {num(c.hours_per_equivalent_day)} h)</>}.
            Equations checked against the thermal library's own steady state: largest difference <strong>{num(c.library_check.max_abs_diff_K, 2)} K</strong>.
          </p>
        </>
      )}
    </Card>
  )
}

function Step() {
  const p = useProfile()
  const [from, setFrom] = useState(0.4)
  const [to, setTo] = useState(1.2)
  const [amb, setAmb] = useState(30)
  const r = useStepResponse(p.body, useDebounced(from, 250), useDebounced(to, 250), useDebounced(amb, 250), 600)
  const d = r.data
  return (
    <Card title="2. Why temperatures lag: response to a load step">
      <p className="muted" style={{ marginBottom: 12 }}>
        The load jumps from one level to another at minute 0. The winding hot spot reacts in minutes; the oil takes hours. This lag is why
        the twin predicts temperatures rather than reading them off a threshold.
      </p>
      <div style={{ display: 'grid', gap: 8, maxWidth: 640, marginBottom: 12 }}>
        <Slider label="Load before" value={from} set={setFrom} min={0} max={1.5} step={0.05} unit="pu" />
        <Slider label="Load after" value={to} set={setTo} min={0} max={1.5} step={0.05} unit="pu" />
        <Slider label="Ambient" value={amb} set={setAmb} min={0} max={50} step={1} unit="°C" digits={0} />
      </div>
      {r.isError && <Note tone="error">{r.error.message}</Note>}
      {d ? (
        <XYChart
          xTitle="minutes after the step" yTitle="°C"
          traces={[
            { name: 'Hot spot', x: d.t_min, y: d.hot_spot_C, color: '#8a8d93' },
            { name: 'Top oil', x: d.t_min, y: d.top_oil_C, color: '#0b0b0c', dash: 'dash' },
          ]}
          vlines={[{ x: d.time_constants_min.oil, label: `oil time constant ${d.time_constants_min.oil} min` }]}
        />
      ) : <Skeleton h={260} />}
      {d && (
        <p className="muted">
          Settles at {num(d.final.top_oil_C)} °C oil and {num(d.final.hot_spot_C)} °C hot spot. Time constants: oil {d.time_constants_min.oil} min, winding {d.time_constants_min.winding} min.
        </p>
      )}
    </Card>
  )
}

function WhatIf() {
  const s = useSession()
  const [load, setLoad] = useState(1.2)
  const [amb, setAmb] = useState(0)
  const [rise, setRise] = useState(1.0)
  const [model, setModel] = useState<'iec' | 'detailed'>('iec')
  const [kf, setKf] = useState(1)
  const kfDebounced = useDebounced(kf, 350)
  const timeSeries = !!s.run && s.run.mode !== 'snapshot' && s.run.mode !== 'data_only'
  const w = useWhatIf(s.datasetId, useDebounced(load, 350), useDebounced(amb, 350), useDebounced(rise, 350), timeSeries, model, model === 'detailed' ? kfDebounced : 1)
  const range = useMemo<[number, number] | null>(() => {
    const t = w.data ? times(w.data.series.base_hot_spot_C ?? { t: [], v: [] }) : []
    return t.length ? [t[0], t[t.length - 1]] : null
  }, [w.data])
  const sum = w.data?.summary as { base: Record<string, number | null>; whatif: Record<string, number | null>; note: string } | undefined
  const rows: [string, string, number, string?][] = [
    ['Peak top oil', 'peak_top_oil_C', 1, '°C'],
    ['Peak hot spot', 'peak_hot_spot_C', 1, '°C'],
    ['Hours with hot spot above 98 °C', 'hours_hot_spot_above_98C', 1, 'h'],
    ['Mean ageing rate', 'mean_ageing_rate', 2, '× normal'],
    ['Insulation life used in the window', 'equivalent_days_used', 2, 'days'],
    ['Years to reference life at this rate', 'years_to_reference_life_at_this_rate', 1, 'years'],
  ]
  return (
    <Card title="3. What if? Replay this dataset under different conditions">
      <p className="muted" style={{ marginBottom: 12 }}>
        Takes <strong>{s.run?.name ?? 'the selected dataset'}</strong>'s own load and weather history and runs the same physics again with changes. This is
        what a dashboard of thresholds cannot do.
      </p>
      {!timeSeries ? (
        <Note tone="info">The selected dataset has no load and ambient time series to replay. Choose a scenario in the top bar.</Note>
      ) : (
        <>
          <div style={{ display: 'grid', gap: 8, maxWidth: 640, marginBottom: 12 }}>
            <Slider label="Load" value={load} set={setLoad} min={0.5} max={1.6} step={0.05} unit="× actual" />
            <Slider label="Ambient" value={amb} set={setAmb} min={-5} max={20} step={1} unit="°C hotter" digits={0} />
            <Slider label="Cooling (oil rise)" value={rise} set={setRise} min={0.8} max={1.6} step={0.05} unit="× rise" />
            <label className="slider">
              <span>Physics model</span>
              <select value={model} onChange={(e) => { setModel(e.target.value as 'iec' | 'detailed'); if (e.target.value === 'iec') setKf(1) }}>
                <option value="iec">Standard (IEC 60076-7)</option>
                <option value="detailed">Detailed heat balance</option>
              </select>
              <span />
            </label>
            {model === 'detailed' && <Slider label="Harmonics (K-factor)" value={kf} set={setKf} min={1} max={12} step={0.5} unit="K" digits={1} />}
          </div>
          {w.isError && <Note tone="error">{w.error.message}</Note>}
          {w.data && range && (
            <>
              <TimeChart
                range={range} cursor={null} clip={false} yTitle="Hot spot °C" height={260}
                traces={[
                  { name: 'As recorded', series: w.data.series.base_hot_spot_C, color: '#0b0b0c', width: 1.2 },
                  { name: 'What if', series: w.data.series.whatif_hot_spot_C, color: '#8a8d93', width: 1.4 },
                ]}
                hlines={[{ y: 98, label: 'ageing rate 1 at 98 °C' }]}
              />
              {sum && (
                <table className="compare" style={{ marginTop: 12 }}>
                  <thead><tr><th>Over {num(sum.base.window_days, 0)} days</th><th>As recorded</th><th>What if</th><th>Change</th></tr></thead>
                  <tbody>
                    {rows.map(([label, key, d, unit]) => {
                      const a = sum.base[key], b = sum.whatif[key]
                      const delta = typeof a === 'number' && typeof b === 'number' ? b - a : null
                      return (
                        <tr key={key}>
                          <td>{label}</td>
                          <td className="num">{key.startsWith('years') ? years(a) : num(a, d)} {unit}</td>
                          <td className="num">{key.startsWith('years') ? years(b) : num(b, d)} {unit}</td>
                          <td className="num delta">{delta == null || key.startsWith('years') && (Number(a) > 40 || Number(b) > 40) ? '—' : `${delta >= 0 ? '+' : ''}${delta.toFixed(d)}`}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              )}
              <p className="muted" style={{ marginTop: 8 }}>{sum?.note}</p>
            </>
          )}
          {!w.data && !w.isError && <Skeleton h={260} />}
        </>
      )}
    </Card>
  )
}

const LOSS_PARTS: ['core' | 'i2r' | 'eddy' | 'stray', string, string][] = [
  ['core', 'Core (no-load)', '#c8cacd'], ['i2r', 'Winding copper (I²R)', '#0b0b0c'], ['eddy', 'Eddy', '#6b6e75'], ['stray', 'Stray', '#a9acb1'],
]

function LossBar({ row }: { row: { core: number; i2r: number; eddy: number; stray: number; total: number; winding_temp_C: number } }) {
  return (
    <>
      <div className="lossbar" role="img" aria-label={`Total loss ${row.total} watts`}>
        {LOSS_PARTS.map(([k, label, c]) => <span key={k} style={{ width: `${(row[k] / row.total) * 100}%`, background: c }} title={`${label}: ${row[k]} W`} />)}
      </div>
      <div className="losslegend">
        {LOSS_PARTS.map(([k, label, c]) => <span key={k}><i style={{ background: c }} />{label} {row[k].toLocaleString('en-GB')} W</span>)}
      </div>
      <p className="muted" style={{ marginTop: 4 }}>Total {row.total.toLocaleString('en-GB')} W, winding at {row.winding_temp_C} °C.</p>
    </>
  )
}

function Detailed() {
  const p = useProfile()
  const [from, setFrom] = useState(0.4)
  const [to, setTo] = useState(1.2)
  const [amb, setAmb] = useState(30)
  const [kf, setKf] = useState(1)
  const [mass, setMass] = useState(false)
  const r = useDetailed(p.body, { fromPu: useDebounced(from, 300), toPu: useDebounced(to, 300), ambientC: useDebounced(amb, 300), minutes: 720, kFactor: useDebounced(kf, 300), useMass: mass })
  const d = r.data
  const tc = d?.time_constants
  return (
    <Card title="4. A second opinion: a heat-balance model with real losses">
      <p className="muted" style={{ marginBottom: 12 }}>
        The standard model above is a fixed-time-constant lag towards an exponent formula. This one starts from the heat balance of the oil: losses in, a
        nonlinear cooling law out. Winding copper loss rises with temperature, eddy loss falls, harmonic currents add loss, and thicker (colder) oil widens the
        winding-to-oil gradient. Where the two models agree the physics is solid; where they part company is the model uncertainty. The twin can run either
        one as the &quot;real&quot; transformer in a simulation (see the profile page).
      </p>
      <div style={{ display: 'grid', gap: 8, maxWidth: 640, marginBottom: 12 }}>
        <Slider label="Load before" value={from} set={setFrom} min={0} max={1.5} step={0.05} unit="pu" />
        <Slider label="Load after" value={to} set={setTo} min={0} max={1.5} step={0.05} unit="pu" />
        <Slider label="Ambient" value={amb} set={setAmb} min={0} max={50} step={1} unit="°C" digits={0} />
        <Slider label="Harmonics (K-factor)" value={kf} set={setKf} min={1} max={12} step={0.5} unit="K" digits={1} />
        <label className="row" style={{ gap: 6, fontSize: 13 }}>
          <input type="checkbox" checked={mass} onChange={(e) => setMass(e.target.checked)} /> Take the oil time constant from the nameplate masses
        </label>
      </div>
      {r.isError && <Note tone="error">{r.error.message}</Note>}
      {d ? (
        <>
          <XYChart
            xTitle="minutes after the step" yTitle="°C"
            traces={[
              { name: 'Hot spot, detailed', x: d.t_min, y: d.detailed.hot_spot_C, color: '#0b0b0c' },
              { name: 'Hot spot, standard', x: d.t_min, y: d.iec.hot_spot_C, color: '#8a8d93' },
              { name: 'Top oil, detailed', x: d.t_min, y: d.detailed.top_oil_C, color: '#0b0b0c', dash: 'dash' },
              { name: 'Top oil, standard', x: d.t_min, y: d.iec.top_oil_C, color: '#8a8d93', dash: 'dash' },
            ]}
            height={300}
          />
          <div className="grid grid--2" style={{ marginTop: 12 }}>
            <div>
              <table className="compare">
                <thead><tr><th>Settled values</th><th>Standard</th><th>Detailed</th></tr></thead>
                <tbody>
                  <tr><td>Top oil</td><td className="num">{num(d.steady_after.iec.top_oil_C)} °C</td><td className="num">{num(d.steady_after.detailed.top_oil_C)} °C</td></tr>
                  <tr><td>Hot spot</td><td className="num">{num(d.steady_after.iec.hot_spot_C)} °C</td><td className="num">{num(d.steady_after.detailed.hot_spot_C)} °C</td></tr>
                  <tr><td>Oil reaches 63 % of the step in</td><td className="num">{tc?.iec_63pct_min ?? '—'} min</td><td className="num">{tc?.detailed_63pct_min ?? '—'} min</td></tr>
                </tbody>
              </table>
              <p className="muted" style={{ marginTop: 8 }}>
                Oil viscosity is {d.viscosity.ratio_before}× its rated-condition value before the step and {d.viscosity.ratio_after}× after. {d.viscosity.note}
              </p>
              {tc?.implied_by_masses && (
                <p className="muted" style={{ marginTop: 6 }}>
                  The nameplate masses imply an oil time constant of about <strong style={{ color: 'var(--text)' }}>{tc.implied_by_masses.tau_h} h</strong> ({tc.implied_by_masses.thermal_capacity_Wh_per_K} Wh/K), against {tc.iec_nominal_min / 60} h used by default. {tc.implied_by_masses.note}
                </p>
              )}
            </div>
            <div>
              <h3 style={{ marginBottom: 6 }}>Where the losses go: before the step</h3>
              <LossBar row={d.losses.before} />
              <h3 style={{ margin: '14px 0 6px' }}>After the step</h3>
              <LossBar row={d.losses.after} />
            </div>
          </div>
          <p className="muted" style={{ marginTop: 8 }}>{d.assumptions.note}</p>
        </>
      ) : <Skeleton h={300} />}
    </Card>
  )
}

function AgeingModels() {
  const q = useAgeingModels()
  const d = q.data
  const COLORS = ['#0b0b0c', '#8a8d93', '#55595f', '#a9acb1']
  return (
    <Card title="5. How fast does insulation age? Two laws, side by side">
      <p className="muted" style={{ marginBottom: 12 }}>
        The IEC 6 K rule doubles the ageing rate every 6 K and is a straight line on a log scale. The Arrhenius law (the chemistry behind it) curves.
        They agree near 98 °C and part company away from it, so predicted life at very high hot-spot temperatures depends on which law you trust.
      </p>
      {q.isError && <Note tone="error">{q.error.message}</Note>}
      {d ? (
        <>
          <XYChart
            logY xTitle="hot-spot temperature °C" yTitle="relative ageing rate (1 = design)" height={300}
            traces={d.models.map((m, i) => ({ name: m.label, x: d.hot_spot_C, y: m.rate, color: COLORS[i % COLORS.length], dash: i === 1 ? ('dot' as const) : i === 3 ? ('dash' as const) : ('solid' as const) }))}
            vlines={[{ x: 98, label: '98 °C' }, { x: 120, label: '120 °C limit' }]}
          />
          <p className="muted" style={{ marginTop: 8 }}>{d.note}</p>
        </>
      ) : <Skeleton h={300} />}
    </Card>
  )
}

export default function Physics() {
  const p = useProfile()
  return (
    <>
      <PageTitle title="Physics" sub="The model behind the twin, made visible: IEC 60076-7 thermal model and insulation ageing." />
      <Note tone="info">
        These are the standard's equations with <strong>{p.typed.name || 'this transformer'}</strong>'s numbers
        {p.typed.rating_kVA ? ` (${p.typed.rating_kVA} kVA)` : ''}, run by the same library the twin uses. The model is not fitted to data. There is no
        heat-run test data yet to validate it against, so treat the numbers as the standard's prediction, not a measurement.
      </Note>
      <Chain />
      <Step />
      <WhatIf />
      <Detailed />
      <AgeingModels />
    </>
  )
}
