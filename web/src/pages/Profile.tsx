import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { usePresets, useResolvedProfile, useSimulate } from '../api/client'
import { Card, Note, PageTitle, Skeleton } from '../components/ui'
import { useProfile } from '../context/Profile'
import { useSession } from '../context/Session'
import { useDebounced } from '../lib/useDebounced'

const SCENARIOS: [string, string][] = [
  ['N', 'Normal (healthy month)'],
  ['S1', 'S1 · Overload'],
  ['S2', 'S2 · Cooling degradation'],
  ['S3', 'S3 · Phase unbalance'],
  ['S4a', 'S4a · Oil leak'],
  ['S4b', 'S4b · Oil theft'],
  ['S5', 'S5 · Through-faults'],
]

interface Field { key: string; label: string; unit?: string; type?: 'text' | 'select'; options?: string[]; help?: string }

const BASIC: Field[] = [
  { key: 'name', label: 'Name', type: 'text' },
  { key: 'rating_kVA', label: 'Rating', unit: 'kVA' },
  { key: 'lv_voltage_V', label: 'LV voltage', unit: 'V', help: 'Line-to-line, no load' },
  { key: 'hv_voltage_V', label: 'HV voltage', unit: 'V' },
  { key: 'cooling', label: 'Cooling', type: 'select', options: ['ONAN', 'ONAF'] },
]
const LOSSES: Field[] = [
  { key: 'load_loss_W', label: 'Load loss at rated load', unit: 'W' },
  { key: 'no_load_loss_W', label: 'No-load loss', unit: 'W' },
  { key: 'total_loss_100_W', label: 'Total loss at 100 % load', unit: 'W', help: 'Used only if the two losses above are blank' },
  { key: 'total_loss_50_W', label: 'Total loss at 50 % load', unit: 'W' },
]
const THERMAL: Field[] = [
  { key: 'top_oil_rise_K', label: 'Top-oil rise at rated load', unit: 'K', help: 'Nameplate "temp rise, oil"' },
  { key: 'winding_oil_gradient_K', label: 'Winding-to-oil gradient', unit: 'K' },
  { key: 'hot_spot_factor', label: 'Hot-spot factor H' },
  { key: 'oil_time_constant_min', label: 'Oil time constant', unit: 'min' },
  { key: 'winding_time_constant_min', label: 'Winding time constant', unit: 'min' },
  { key: 'oil_exponent_x', label: 'Oil exponent x' },
  { key: 'winding_exponent_y', label: 'Winding exponent y' },
  { key: 'amb_temp_surcharge_K', label: 'Ambient surcharge', unit: 'K' },
]
const AGE: Field[] = [
  { key: 'manufacture_year', label: 'Year of manufacture' },
  { key: 'manufacture_month', label: 'Month of manufacture' },
  { key: 'years_in_service', label: 'Years in service', help: 'Used only if no manufacture year' },
]

// Source tags are never green/yellow/red: those colours mean health state only.
const TAG_CLASS = (tag: string | undefined) =>
  !tag ? '' : /confirmed|user/i.test(tag) ? 'tag--given' : /calculated|derived/i.test(tag) ? 'tag--calc' : 'tag--assumed'

export function TagChip({ tag }: { tag: string | undefined }) {
  if (!tag) return null
  return <span className={`tag ${TAG_CLASS(tag)}`}>{tag}</span>
}

export default function ProfilePage() {
  const nav = useNavigate()
  const s = useSession()
  const p = useProfile()
  const presets = usePresets()
  const resolved = useResolvedProfile(useDebounced(p.body, 400))
  const sim = useSimulate()
  const [scenario, setScenario] = useState('S2')
  const [plant, setPlant] = useState<'iec' | 'detailed'>('iec')
  const [err, setErr] = useState<string | null>(null)

  const ph = (key: string) => {
    const v = resolved.data?.values?.[key]
    return v == null || p.typed[key] ? '' : String(v)
  }
  const tag = (key: string) => resolved.data?.tags?.[key]

  const input = (f: Field) => (
    <label key={f.key} className="field">
      <span>{f.label}{f.unit && <span className="muted"> ({f.unit})</span>}</span>
      {f.type === 'select' ? (
        <select value={p.typed[f.key] ?? ''} onChange={(e) => p.setField(f.key, e.target.value)}>
          <option value="">{ph(f.key) ? `default: ${ph(f.key)}` : '—'}</option>
          {f.options!.map((o) => <option key={o}>{o}</option>)}
        </select>
      ) : (
        <input
          type={f.type === 'text' ? 'text' : 'number'} step="any" value={p.typed[f.key] ?? ''} placeholder={ph(f.key)}
          onChange={(e) => p.setField(f.key, e.target.value)}
        />
      )}
      <span className="field__tag"><TagChip tag={tag(f.key)} />{f.help && <span className="muted"> {f.help}</span>}</span>
    </label>
  )

  async function run() {
    setErr(null)
    if (!p.body) return
    try {
      const ds = await sim.mutateAsync({ ...p.body, scenario, name: undefined, plant })
      s.setDatasetId(ds.dataset_id)
      nav('/')
    } catch (e) {
      setErr((e as Error).message)
    }
  }

  const v = resolved.data?.values
  return (
    <>
      <PageTitle title="Transformer profile" sub="One model for any distribution transformer: enter the rating and whatever else the nameplate says." />
      <Note tone="info">
        The twin is physics (IEC 60076-7), not fitted to one unit. Rating and voltage are enough; every other value falls back to a standard default
        and is tagged as such. <strong>A nameplate value always beats a default.</strong>
      </Note>

      <Card title="Start from an example">
        {presets.isLoading ? <Skeleton h={40} /> : (
          <div className="row">
            {presets.data?.map((x) => (
              <button key={x.id} type="button" className={`btn ${p.presetId === x.id ? 'btn--primary' : ''}`} onClick={() => p.applyPreset(x.id)} title={x.description}>
                {x.label}
              </button>
            ))}
          </div>
        )}
        {p.presetId && <p className="muted" style={{ marginTop: 8 }}>{presets.data?.find((x) => x.id === p.presetId)?.description}</p>}
      </Card>

      <div className="grid grid--2">
        <Card title="Rating and nameplate">
          <div className="fields">{BASIC.map(input)}</div>
          <h3 style={{ margin: '16px 0 8px' }}>Losses</h3>
          <div className="fields">{LOSSES.map(input)}</div>
          <h3 style={{ margin: '16px 0 8px' }}>Age</h3>
          <div className="fields">{AGE.map(input)}</div>
        </Card>
        <Card title="Thermal parameters (blank = standard default)">
          <div className="fields">{THERMAL.map(input)}</div>
        </Card>
      </div>

      <Card title="What the twin will use">
        {resolved.isError && <Note tone="error">{resolved.error.message}</Note>}
        {!p.ready && <p className="muted">Enter a rating (kVA) to see the complete profile.</p>}
        {v && (
          <>
            <dl className="kv">
              <dt>Rated current (LV)</dt><dd>{String(v.i_rated_A)} A <TagChip tag={tag('i_rated_A')} /></dd>
              <dt>Load loss / no-load loss</dt><dd>{String(v.load_loss_W)} W / {String(v.no_load_loss_W)} W <TagChip tag={tag('load_loss_W')} /></dd>
              <dt>Loss ratio R</dt><dd>{(Number(v.load_loss_W) / Number(v.no_load_loss_W)).toFixed(2)}</dd>
              <dt>Top-oil rise / winding gradient</dt><dd>{String(v.top_oil_rise_K)} K / {String(v.winding_oil_gradient_K)} K <TagChip tag={tag('top_oil_rise_K')} /></dd>
              <dt>Time constants (oil / winding)</dt><dd>{String(v.oil_time_constant_min)} min / {String(v.winding_time_constant_min)} min <TagChip tag={tag('oil_time_constant_min')} /></dd>
            </dl>
            {resolved.data!.notes.length > 0 && (
              <ul style={{ margin: '12px 0 0', paddingLeft: 18 }}>
                {resolved.data!.notes.map((n) => <li key={n} className="muted">{n}</li>)}
              </ul>
            )}
          </>
        )}
      </Card>

      <Card title="Try it: simulate a scenario on this transformer">
        <p className="muted">
          Generates a month of load, weather and sensor data for <strong>this</strong> rating (labelled SIMULATED), injects the chosen fault, and runs the
          whole pipeline: twin, residual baseline, analytics. The same scenarios run for any size. With <strong>detailed</strong> plant physics the simulated
          transformer runs an independent heat-balance model, so the twin is tested against different physics, not just different numbers.
        </p>
        <div className="row" style={{ marginTop: 12 }}>
          <select value={scenario} onChange={(e) => setScenario(e.target.value)} aria-label="Scenario">
            {SCENARIOS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
          <select value={plant} onChange={(e) => setPlant(e.target.value as 'iec' | 'detailed')} aria-label="Physics of the simulated transformer">
            <option value="iec">Plant physics: standard (IEC, perturbed)</option>
            <option value="detailed">Plant physics: detailed heat balance</option>
          </select>
          <button className="btn btn--primary" type="button" onClick={run} disabled={!p.ready || sim.isPending}>
            {sim.isPending ? 'Simulating…' : 'Simulate and open Overview'}
          </button>
        </div>
        {err && <div style={{ marginTop: 12 }}><Note tone="error">{err}</Note></div>}
      </Card>
    </>
  )
}
