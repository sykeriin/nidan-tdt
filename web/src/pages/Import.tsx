import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { inspectFiles, useLoadDataset, type InspectResult, type LoadArgs } from '../api/client'
import { Card, DataTable, Note, PageTitle } from '../components/ui'
import { useSession } from '../context/Session'

// Canonical channels a column can be mapped to (contracts/canonical.py).
const CANONICAL: [string, string][] = [
  ['IR', 'Current R (A)'], ['IY', 'Current Y (A)'], ['IB', 'Current B (A)'], ['I_mean', 'Mean current (A)'], ['IN', 'Neutral current (A)'],
  ['VR', 'Voltage R-N (V)'], ['VY', 'Voltage Y-N (V)'], ['VB', 'Voltage B-N (V)'],
  ['VRY', 'Voltage R-Y (V)'], ['VYB', 'Voltage Y-B (V)'], ['VBR', 'Voltage B-R (V)'],
  ['S_kVA', 'Apparent power (kVA)'], ['P_kW', 'Active power (kW)'], ['Q_kVAr', 'Reactive power (kVAr)'], ['PF', 'Power factor'], ['freq_Hz', 'Frequency (Hz)'],
  ['loading_pct', 'Loading (%)'],
  ['OTI_C', 'Top-oil temperature (°C)'], ['WTI_C', 'Winding temperature (°C)'], ['ATI_C', 'Ambient (device) (°C)'], ['amb_C', 'Ambient (°C)'],
  ['RH_pct', 'Humidity (%)'], ['OLI_pct', 'Oil level (%)'],
]

interface Proposal {
  source: string
  canonical: string | null
  proposed: string | null
  confidence: number
  unit: string | null
  unit_options: string[]
}
interface Row { to: string; unit: string }
type Assetmode = 'default' | 'custom' | 'estimate'

const LOW = 0.6

export default function ImportPage() {
  const nav = useNavigate()
  const s = useSession()
  const load = useLoadDataset()
  const [files, setFiles] = useState<File[]>([])
  const [info, setInfo] = useState<InspectResult | null>(null)
  const [rows, setRows] = useState<Record<string, Row>>({})
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [over, setOver] = useState(false)
  const [name, setName] = useState('')
  const [assetMode, setAssetMode] = useState<Assetmode>('default')
  const [kvaText, setKvaText] = useState('1000')
  const [voltsText, setVoltsText] = useState('415')
  const latest = useRef(0)
  const [interval, setIntervalText] = useState('15min')
  const [assignTime, setAssignTime] = useState(false)

  const proposals = (info?.proposals ?? []) as unknown as Proposal[]
  const noTime = info ? (info.timestamp as { column?: string | null }).column == null : false
  const kva = Number(kvaText)
  const volts = Number(voltsText)
  const ratingOk = Number.isFinite(kva) && kva > 0 && Number.isFinite(volts) && volts > 0
  const iRated = ratingOk ? Math.round((kva * 1000) / (Math.sqrt(3) * volts)) : null
  const assignOk = !(noTime && assignTime) || interval.trim() !== ''
  const canSubmit = files.length > 0 && !load.isPending && !busy && assignOk && (assetMode !== 'custom' || ratingOk)

  async function pick(list: FileList | File[]) {
    const f = Array.from(list)
    if (!f.length) return
    const id = ++latest.current
    setFiles(f)
    setInfo(null)
    setErr(null)
    setBusy(true)
    try {
      const r = await inspectFiles(f)
      if (id !== latest.current) return   // a newer file was chosen while this one was being read
      setInfo(r)
      setName(f[0].name.replace(/\.[^.]+$/, ''))
      const next: Record<string, Row> = {}
      for (const p of r.proposals as unknown as Proposal[]) {
        next[p.source] = { to: p.canonical ?? 'ignore', unit: p.unit ?? '' }
      }
      setRows(next)
    } catch (e) {
      if (id === latest.current) setErr((e as Error).message)
    } finally {
      if (id === latest.current) setBusy(false)
    }
  }

  async function submit() {
    setErr(null)
    const mapping: NonNullable<LoadArgs['mapping']> = {}
    for (const [src, r] of Object.entries(rows)) if (r.to !== 'ignore') mapping[src] = { to: r.to, ...(r.unit ? { unit: r.unit } : {}) }
    const args: LoadArgs = {
      files, name: name || undefined, mapping,
      asset: assetMode === 'estimate' ? 'estimate' : assetMode === 'custom' ? { rating_kVA: kva, lv_voltage_V: volts } : undefined,
      interval: noTime && assignTime && interval ? interval : undefined,
    }
    try {
      const ds = await load.mutateAsync(args)
      s.setDatasetId(ds.dataset_id)
      nav('/data-health')
    } catch (e) {
      setErr((e as Error).message)
    }
  }

  const set = (src: string, patch: Partial<Row>) => setRows((r) => ({ ...r, [src]: { ...r[src], ...patch } }))

  return (
    <>
      <PageTitle title="Import" sub="Load your own data: upload, confirm the column mapping, run. Any reasonable transformer dataset should work." />

      <div
        className={`drop ${over ? 'drop--over' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files) }}
      >
        <p><strong>Drag CSV or Excel files here</strong>, or</p>
        <label className="btn btn--primary" style={{ marginTop: 8, cursor: 'pointer' }}>
          Choose files
          <input type="file" multiple accept=".csv,.tsv,.txt,.xlsx,.xlsm,.xls" hidden onChange={(e) => { if (e.target.files) pick(e.target.files); e.target.value = '' }} />
        </label>
        {files.length > 0 && <p className="muted" style={{ marginTop: 8 }}>{files.map((f) => f.name).join(', ')}</p>}
      </div>

      {busy && <Note tone="info">Reading and mapping the file…</Note>}
      {err && <Note tone="error">{err}</Note>}

      {info && (
        <>
          {info.warnings.map((w) => <Note key={w} tone="warn">{w}</Note>)}

          <Card title="What was found">
            <DataTable table={{ columns: ['name', 'role', 'rows'], rows: info.tables as Record<string, unknown>[] }} />
            <p className="muted" style={{ marginTop: 8 }}>
              {noTime
                ? 'No timestamp column found: these are records without time (snapshot mode).'
                : `Time column: ${(info.timestamp as { column?: string }).column}, format ${(info.timestamp as { format?: string }).format?.replace('_', '-')}, ${(info.timestamp as { parsed_ok_pct?: number }).parsed_ok_pct}% parsed.`}
            </p>
            {noTime && (
              <div style={{ marginTop: 8 }}>
                <label className="row" style={{ gap: 6 }}>
                  <input type="radio" name="time" checked={!assignTime} onChange={() => setAssignTime(false)} />
                  Treat as records (snapshot mode: per-record twin view, no time charts)
                </label>
                <label className="row" style={{ gap: 6, marginTop: 4 }}>
                  <input type="radio" name="time" checked={assignTime} onChange={() => setAssignTime(true)} />
                  Assign times: interval
                  <input type="text" value={interval} onChange={(e) => setIntervalText(e.target.value)} style={{ width: 90 }} disabled={!assignTime} aria-label="Interval" />
                  <span className="muted">(for example 15min; assigned times are flagged as assumed)</span>
                </label>
              </div>
            )}
          </Card>

          <Card title="Column mapping">
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Source column</th><th>Maps to</th><th>Unit</th><th>Confidence</th></tr></thead>
                <tbody>
                  {proposals.map((p) => {
                    const r = rows[p.source] ?? { to: 'ignore', unit: '' }
                    const low = p.confidence < LOW
                    return (
                      <tr key={p.source}>
                        <td>{p.source}</td>
                        <td>
                          <select value={r.to} onChange={(e) => set(p.source, { to: e.target.value })} aria-label={`Map ${p.source} to`}>
                            <option value="ignore">Ignore</option>
                            {CANONICAL.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
                          </select>
                          {low && p.proposed && r.to === 'ignore' && <span className="muted"> suggested: {p.proposed}</span>}
                        </td>
                        <td>
                          {p.unit_options?.length > 1 ? (
                            <select value={r.unit} onChange={(e) => set(p.source, { unit: e.target.value })} aria-label={`Unit of ${p.source}`}>
                              {p.unit_options.map((u) => <option key={u} value={u}>{u}</option>)}
                            </select>
                          ) : (p.unit ?? '—')}
                        </td>
                        <td className={`conf ${low ? 'conf--low' : ''}`}>{p.confidence.toFixed(2)}{low ? ' · check' : ''}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title="Transformer rating">
            <div className="row">
              {([['default', 'Transformer-1 (asset.yaml)'], ['custom', 'Enter rating'], ['estimate', 'Estimate from data']] as [Assetmode, string][]).map(([id, label]) => (
                <label key={id} className="row" style={{ gap: 6 }}>
                  <input type="radio" name="asset" checked={assetMode === id} onChange={() => setAssetMode(id)} /> {label}
                </label>
              ))}
            </div>
            {assetMode === 'custom' && (
              <div className="row" style={{ marginTop: 12 }}>
                <label className="muted">Rated kVA <input type="number" value={kvaText} min={1} onChange={(e) => setKvaText(e.target.value)} aria-invalid={!ratingOk} /></label>
                <label className="muted">LV voltage (V) <input type="number" value={voltsText} min={1} onChange={(e) => setVoltsText(e.target.value)} aria-invalid={!ratingOk} /></label>
                <span className="muted">Rated current: <strong className="num">{iRated == null ? '— (enter a positive rating)' : `${iRated} A`}</strong></span>
              </div>
            )}
            {assetMode === 'estimate' && <p className="muted" style={{ marginTop: 8 }}>The rating is estimated from the data and shown with a red banner: rating-dependent values become assumptions.</p>}
          </Card>

          <Card title="Preview (first 10 rows)">
            <DataTable table={info.preview} limit={10} />
          </Card>

          <div className="row">
            <label className="muted">Dataset name <input type="text" value={name} onChange={(e) => setName(e.target.value)} style={{ marginLeft: 6, width: 220 }} /></label>
            <button className="btn btn--primary" type="button" onClick={submit} disabled={!canSubmit}>
              {load.isPending ? 'Running the twin…' : 'Load and run'}
            </button>
          </div>
        </>
      )}
    </>
  )
}
