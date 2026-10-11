// Workbench: the generic-transformer tools that sit beside the live twin. Profile (any rating), Physics (calculation chain and
// load-step lag), Outlook (diagnosis, remaining life, 24 h forecast), Report downloads and the CPRI-format self-test.
// Every number comes from the backend; this file only lays it out.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  reportHref, simulateScenario, useBrief, useChain, useOutlook, usePresets, useResolvedProfile, useSelfTest, useStepResponse,
  type ProfileBody,
} from "../api/client";
import { LineChart } from "./LineChart";
import { AnomalyTests } from "./AnomalyTests";

export type WbTab = "profile" | "physics" | "outlook" | "anomaly" | "report" | "selftest";
const TABS: { id: WbTab; label: string; hint: string }[] = [
  { id: "profile", label: "Profile", hint: "Any rating" },
  { id: "physics", label: "Physics", hint: "Load to ageing" },
  { id: "outlook", label: "Outlook", hint: "Diagnosis, life" },
  { id: "anomaly", label: "Anomaly tests", hint: "21 alert types" },
  { id: "report", label: "Report", hint: "HTML, CSV, JSON" },
  { id: "selftest", label: "Self-test", hint: "CPRI format" },
];

// ---------------------------------------------------------------- the active profile (typed values + provenance tags)
const TEXT_FIELDS = new Set(["name", "site", "cooling", "vector_group", "insulation", "breather"]);
type Typed = Record<string, string>;
interface PState { typed: Typed; tags: Record<string, string>; presetId: string | null }
const KEY = "dt.workbench.profile";
const load = (): PState | null => { try { const r = localStorage.getItem(KEY); return r ? JSON.parse(r) : null; } catch { return null; } };

function toBody(typed: Typed, tags: Record<string, string>): ProfileBody {
  const values: Record<string, unknown> = {}, keep: Record<string, string> = {};
  for (const [k, raw] of Object.entries(typed)) {
    const v = raw.trim();
    if (v === "") continue;
    values[k] = TEXT_FIELDS.has(k) ? v : Number(v);
    if (tags[k]) keep[k] = tags[k];
  }
  return { values, tags: keep };
}

function useProfileState() {
  const presets = usePresets();
  const [state, setState] = useState<PState | null>(load);
  useEffect(() => {
    if (state || !presets.data) return;
    const p = presets.data.find((x) => x.id === "transformer-1") ?? presets.data[0];
    if (p) setState({ typed: Object.fromEntries(Object.entries(p.values).map(([k, v]) => [k, String(v)])), tags: p.tags, presetId: p.id });
  }, [presets.data, state]);
  useEffect(() => { if (state) try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* not remembered */ } }, [state]);
  const body = useMemo(() => (state ? toBody(state.typed, state.tags) : null), [state]);
  const ready = !!body && ("rating_kVA" in body.values || "i_rated_A" in body.values);
  return {
    typed: state?.typed ?? {}, presetId: state?.presetId ?? null, presets: presets.data ?? [], ready, body: ready ? body : null,
    setField: (k: string, v: string) => setState((s) => s && { typed: { ...s.typed, [k]: v }, tags: Object.fromEntries(Object.entries(s.tags).filter(([t]) => t !== k)), presetId: s.presetId }),
    applyPreset: (id: string) => { const p = presets.data?.find((x) => x.id === id); if (p) setState({ typed: Object.fromEntries(Object.entries(p.values).map(([k, v]) => [k, String(v)])), tags: p.tags, presetId: p.id }); },
  };
}
type ProfileApi = ReturnType<typeof useProfileState>;

function useDebounced<T>(v: T, ms = 300): T {
  const [d, setD] = useState(v);
  useEffect(() => { const h = setTimeout(() => setD(v), ms); return () => clearTimeout(h); }, [v, ms]);
  return d;
}
const num = (v: unknown, d = 1) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(d) : "—");
const years = (v: unknown) => (typeof v === "number" && v > 40 ? "> 40" : num(v, 1));

function Section({ title, code, children }: { title: string; code?: string; children: ReactNode }) {
  return (
    <section className="schedule wb-sec">
      <header className="schedule-head"><h2>{title}</h2>{code && <span className="code">{code}</span>}</header>
      <div className="wb-body">{children}</div>
    </section>
  );
}
const Note = ({ children, err }: { children: ReactNode; err?: boolean }) => <p className={`wb-note${err ? " err" : ""}`} role={err ? "alert" : undefined}>{children}</p>;

function Slider({ label, value, set, min, max, step, unit, digits = 2 }: { label: string; value: number; set: (v: number) => void; min: number; max: number; step: number; unit: string; digits?: number }) {
  return (
    <label className="wb-slider">
      <span>{label}</span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => set(Number(e.target.value))} />
      <output>{value.toFixed(digits)} {unit}</output>
    </label>
  );
}

// ---------------------------------------------------------------- Profile
interface Field { key: string; label: string; unit?: string; select?: string[]; text?: boolean; help?: string }
const BASIC: Field[] = [
  { key: "name", label: "Name", text: true }, { key: "rating_kVA", label: "Rating", unit: "kVA" },
  { key: "lv_voltage_V", label: "LV voltage", unit: "V", help: "line-to-line" }, { key: "hv_voltage_V", label: "HV voltage", unit: "V" },
  { key: "cooling", label: "Cooling", select: ["ONAN", "ONAF"] },
];
const LOSSES: Field[] = [
  { key: "load_loss_W", label: "Load loss, rated", unit: "W" }, { key: "no_load_loss_W", label: "No-load loss", unit: "W" },
  { key: "total_loss_100_W", label: "Total loss at 100 %", unit: "W", help: "used if the two above are blank" }, { key: "total_loss_50_W", label: "Total loss at 50 %", unit: "W" },
];
const THERMAL: Field[] = [
  { key: "top_oil_rise_K", label: "Top-oil rise, rated", unit: "K" }, { key: "winding_oil_gradient_K", label: "Winding-to-oil gradient", unit: "K" },
  { key: "hot_spot_factor", label: "Hot-spot factor H" }, { key: "oil_time_constant_min", label: "Oil time constant", unit: "min" },
  { key: "winding_time_constant_min", label: "Winding time constant", unit: "min" }, { key: "oil_exponent_x", label: "Oil exponent x" },
  { key: "winding_exponent_y", label: "Winding exponent y" }, { key: "amb_temp_surcharge_K", label: "Ambient surcharge", unit: "K" },
];
const AGE: Field[] = [{ key: "manufacture_year", label: "Year made" }, { key: "manufacture_month", label: "Month made" }, { key: "years_in_service", label: "Years in service" }];
const SCENARIOS: [string, string][] = [["N", "Normal month"], ["S1", "S1 Overload"], ["S2", "S2 Cooling degradation"], ["S3", "S3 Phase unbalance"], ["S4a", "S4a Oil leak"], ["S4b", "S4b Oil theft"], ["S5", "S5 Through-faults"]];

function Tag({ tag }: { tag?: string }) {
  if (!tag) return null;
  const kind = /confirmed|user/i.test(tag) ? "given" : /calculated|derived/i.test(tag) ? "calc" : "assumed";
  return <span className={`wb-tag ${kind}`}>{tag}</span>;
}

function ProfileTab({ p, onSimulated }: { p: ProfileApi; onSimulated: (id: string) => void }) {
  const resolved = useResolvedProfile(useDebounced(p.body, 400));
  const qc = useQueryClient();
  const [scenario, setScenario] = useState("S2");
  const [plant, setPlant] = useState<"iec" | "detailed">("iec");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const v = resolved.data?.values as Record<string, unknown> | undefined;
  const tag = (k: string) => resolved.data?.tags?.[k as keyof typeof resolved.data.tags] as string | undefined;
  const ph = (k: string) => { const x = v?.[k]; return x == null || p.typed[k] ? "" : String(x); };
  const input = (f: Field) => (
    <label key={f.key} className="wb-field">
      <span>{f.label}{f.unit && <em> {f.unit}</em>}</span>
      {f.select ? (
        <select value={p.typed[f.key] ?? ""} onChange={(e) => p.setField(f.key, e.target.value)}>
          <option value="">{ph(f.key) ? `default ${ph(f.key)}` : "—"}</option>
          {f.select.map((o) => <option key={o}>{o}</option>)}
        </select>
      ) : (
        <input type={f.text ? "text" : "number"} step="any" value={p.typed[f.key] ?? ""} placeholder={ph(f.key)} onChange={(e) => p.setField(f.key, e.target.value)} />
      )}
      <small><Tag tag={tag(f.key)} />{f.help && ` ${f.help}`}</small>
    </label>
  );
  const run = async () => {
    if (!p.body) return;
    setBusy(true); setErr(null);
    try {
      const ds = await simulateScenario({ ...p.body, scenario, plant });
      await qc.invalidateQueries({ queryKey: ["datasets"] });
      onSimulated(ds.dataset_id);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <>
      <Note>The twin is IEC 60076-7 physics, not fitted to one unit. Rating and voltage are enough; every other value falls back to a standard default and is tagged. A nameplate value always beats a default.</Note>
      <Section title="Start from an example" code="W-1">
        <div className="wb-row">
          {p.presets.map((x) => (
            <button key={x.id} className={`wb-btn${p.presetId === x.id ? " on" : ""}`} title={x.description} onClick={() => p.applyPreset(x.id)}>{x.label}</button>
          ))}
        </div>
      </Section>
      <div className="wb-cols">
        <Section title="Rating and nameplate" code="W-2">
          <div className="wb-fields">{BASIC.map(input)}</div>
          <h3>Losses</h3><div className="wb-fields">{LOSSES.map(input)}</div>
          <h3>Age</h3><div className="wb-fields">{AGE.map(input)}</div>
        </Section>
        <Section title="Thermal parameters, blank = default" code="W-3">
          <div className="wb-fields">{THERMAL.map(input)}</div>
        </Section>
      </div>
      <Section title="What the twin will use" code="W-4">
        {resolved.isError && <Note err>{(resolved.error as Error).message}</Note>}
        {!p.ready && <Note>Enter a rating (kVA) to see the complete profile.</Note>}
        {v && (
          <table className="wb-kv"><tbody>
            <tr><th>Rated current, LV</th><td>{String(v.i_rated_A)} A</td><td><Tag tag={tag("i_rated_A")} /></td></tr>
            <tr><th>Load loss / no-load loss</th><td>{String(v.load_loss_W)} W / {String(v.no_load_loss_W)} W</td><td><Tag tag={tag("load_loss_W")} /></td></tr>
            <tr><th>Top-oil rise / winding gradient</th><td>{String(v.top_oil_rise_K)} K / {String(v.winding_oil_gradient_K)} K</td><td><Tag tag={tag("top_oil_rise_K")} /></td></tr>
            <tr><th>Time constants, oil / winding</th><td>{String(v.oil_time_constant_min)} / {String(v.winding_time_constant_min)} min</td><td><Tag tag={tag("oil_time_constant_min")} /></td></tr>
          </tbody></table>
        )}
        {resolved.data?.notes?.length ? <ul className="wb-notes">{resolved.data.notes.map((n) => <li key={n}>{n}</li>)}</ul> : null}
      </Section>
      <Section title="Simulate a month on this transformer" code="W-5">
        <Note>Generates a month of load, weather and sensor data for this rating, injects the chosen fault, and runs the whole pipeline. It is labelled simulated and opens as a dataset in the sheet.</Note>
        <div className="wb-row">
          <select value={scenario} onChange={(e) => setScenario(e.target.value)} aria-label="Scenario">{SCENARIOS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}</select>
          <select value={plant} onChange={(e) => setPlant(e.target.value as "iec" | "detailed")} aria-label="Plant physics">
            <option value="iec">Plant: standard IEC</option><option value="detailed">Plant: detailed heat balance</option>
          </select>
          <button className="wb-btn on" disabled={!p.ready || busy} onClick={run}>{busy ? "Simulating…" : "Simulate and open"}</button>
        </div>
        {err && <Note err>{err}</Note>}
      </Section>
    </>
  );
}

// ---------------------------------------------------------------- Physics
function PhysicsTab({ p }: { p: ProfileApi }) {
  const [ld, setLd] = useState(1.0), [amb, setAmb] = useState(30);
  const [from, setFrom] = useState(0.4), [to, setTo] = useState(1.2), [amb2, setAmb2] = useState(30);
  const chain = useChain(p.body, useDebounced(ld, 250), useDebounced(amb, 250));
  const step = useStepResponse(p.body, useDebounced(from, 250), useDebounced(to, 250), useDebounced(amb2, 250), 600);
  const c = chain.data, d = step.data;
  return (
    <>
      {!p.ready && <Note>Enter a rating on the Profile tab first.</Note>}
      <Section title="From load to ageing" code="W-6">
        <Note>Six steps turn a load into insulation wear, using this transformer's own numbers.</Note>
        <div className="wb-sliders">
          <Slider label="Load" value={ld} set={setLd} min={0} max={1.6} step={0.05} unit="pu" />
          <Slider label="Ambient" value={amb} set={setAmb} min={0} max={50} step={1} unit="°C" digits={0} />
        </div>
        {chain.isError && <Note err>{(chain.error as Error).message}</Note>}
        {c && (
          <>
            <ol className="wb-chain">
              {c.steps.map((s, i) => (
                <li key={s.id}>
                  <b>{i + 1}</b><h4>{s.title}</h4>
                  <code>{s.formula}</code><code className="w">{s.working}</code>
                  <span className="val">{num(s.value, s.unit === "× normal" ? 2 : 1)} <em>{s.unit}</em></span>
                  <small>{s.why}</small>
                </li>
              ))}
            </ol>
            <Note>
              At this load the hot spot sits at <strong>{num(c.hot_spot_C)} °C</strong> and the insulation ages <strong>{num(c.ageing_rate, 2)}×</strong> as fast as designed
              {c.hours_per_equivalent_day != null && c.ageing_rate > 1 ? ` (a day of life every ${num(c.hours_per_equivalent_day)} h)` : ""}.
              Checked against the thermal library's own steady state: largest difference {num(c.library_check.max_abs_diff_K, 2)} K.
            </Note>
          </>
        )}
      </Section>
      <Section title="Why temperatures lag: a load step" code="W-7">
        <Note>The hot spot reacts in minutes; the oil takes hours. That lag is why the twin predicts temperatures instead of comparing them to a threshold.</Note>
        <div className="wb-sliders">
          <Slider label="Load before" value={from} set={setFrom} min={0} max={1.5} step={0.05} unit="pu" />
          <Slider label="Load after" value={to} set={setTo} min={0} max={1.5} step={0.05} unit="pu" />
          <Slider label="Ambient" value={amb2} set={setAmb2} min={0} max={50} step={1} unit="°C" digits={0} />
        </div>
        {step.isError && <Note err>{(step.error as Error).message}</Note>}
        {d && (
          <>
            <LineChart xLabel="minutes after the step" yLabel="°C"
              series={[{ name: "Hot spot", x: d.t_min, y: d.hot_spot_C, cls: "twin" }, { name: "Top oil", x: d.t_min, y: d.top_oil_C, cls: "ink", dash: true }]}
              vlines={[{ x: d.time_constants_min.oil, label: `oil τ ${d.time_constants_min.oil} min` }]} />
            <Note>Settles at {num(d.final.top_oil_C)} °C oil and {num(d.final.hot_spot_C)} °C hot spot. Time constants: oil {d.time_constants_min.oil} min, winding {d.time_constants_min.winding} min.</Note>
          </>
        )}
      </Section>
    </>
  );
}

// ---------------------------------------------------------------- Outlook
function OutlookTab({ dataset, t, timeSeries }: { dataset: string; t: string | null; timeSeries: boolean }) {
  const brief = useBrief(dataset, t, timeSeries);
  const outlook = useOutlook(dataset, t, timeSeries);
  const b = brief.data, o = outlook.data;
  if (!timeSeries) return <Note>This dataset has no time axis, so there is no diagnosis or outlook to compute. Pick another dataset.</Note>;
  return (
    <>
      <Section title="Status at the replay cursor" code="W-8">
        <p className={`wb-sentence lv-${b?.level ?? "nodata"}`}>{b ? b.sentence : "Reading the transformer…"}</p>
        {brief.isError && <Note err>{(brief.error as Error).message}</Note>}
        {b && (
          <table className="wb-kv"><tbody>
            {b.kpis.headroom && <tr><th>Spare capacity</th><td>{num(b.kpis.headroom.pu * 100, 0)} % of rating</td><td>at {num(b.kpis.headroom.ambient_C, 0)} °C, set by {b.kpis.headroom.limiting ?? "limits"}</td></tr>}
            {b.kpis.time_to_limit && <tr><th>Time to a limit</th><td>{b.kpis.time_to_limit.status === "reaches_limit" ? `${num(b.kpis.time_to_limit.hours)} h` : b.kpis.time_to_limit.status === "already_reached" ? "reached" : "not reached"}</td><td>at the present load</td></tr>}
            {b.kpis.ageing_rate != null && <tr><th>Ageing speed</th><td>{num(b.kpis.ageing_rate, 2)}× design</td><td /></tr>}
          </tbody></table>
        )}
      </Section>
      <div className="wb-cols">
        <Section title="What the evidence points to" code="W-9">
          {b && b.diagnosis.filter((x) => x.observable && x.evidence >= 0.15).slice(0, 4).map((x) => (
            <div className="wb-bar" key={x.fault}>
              <span>{x.label}</span><span className="pct">{Math.round(x.share * 100)}%</span>
              <i><b style={{ width: `${Math.max(3, x.share * 100)}%` }} /></i><small>{x.why}</small>
            </div>
          ))}
          {b && !b.diagnosis.some((x) => x.observable && x.evidence >= 0.15) && <Note>Nothing stands out: no fault class has meaningful evidence.</Note>}
          {b && b.diagnosis.some((x) => !x.observable) && <Note>Not observable with these inputs: {b.diagnosis.filter((x) => !x.observable).map((x) => x.label.toLowerCase()).join(", ")}.</Note>}
        </Section>
        <Section title="Maintenance work order" code="W-10">
          {b?.advice ? (
            <>
              <p><span className={`wb-prio p-${b.advice.priority}`}>{b.advice.priority}</span> {b.advice.schedule}</p>
              {b.advice.actions.length ? (
                <ol className="wb-actions">{b.advice.actions.slice(0, 3).map((a, i) => (
                  <li key={`${a.action}-${i}`}><strong>{a.action}</strong><small>{a.test ? `Test: ${a.test}. ` : ""}{a.urgency}{a.standard_ref ? `. Ref: ${a.standard_ref}` : ""}</small></li>
                ))}</ol>
              ) : <Note>No action needed beyond routine inspection.</Note>}
              <Note>{b.advice.note}</Note>
            </>
          ) : <Note>No maintenance guidance for this dataset.</Note>}
        </Section>
      </div>
      <Section title="Remaining insulation life" code="W-11">
        {outlook.isError && <Note err>{(outlook.error as Error).message}</Note>}
        {!o && !outlook.isError && <Note>Running 500 simulations…</Note>}
        {o && (
          <>
            <LineChart xLabel="years from now" yLabel="% of reference life used" yMax={100}
              series={[
                { name: "P90", x: o.rul.fan.years, y: o.rul.fan.p90, cls: "faint" }, { name: "Median", x: o.rul.fan.years, y: o.rul.fan.p50, cls: "ink" },
                { name: "P10", x: o.rul.fan.years, y: o.rul.fan.p10, cls: "faint" },
              ]} />
            <table className="wb-kv"><tbody>
              <tr><th>Median remaining life</th><td>{years(o.rul.years_p50)} years</td><td /></tr>
              <tr><th>1 chance in 10 of less than</th><td>{years(o.rul.years_p10)} years</td><td /></tr>
              <tr><th>Chance of a temperature limit in 30 days</th><td>{num(o.trip_risk_30d.probability * 100, o.trip_risk_30d.probability > 0 && o.trip_risk_30d.probability < 0.1 ? 1 : 0)} %</td><td>{o.trip_risk_30d.runs} simulated months</td></tr>
            </tbody></table>
            <Note>{o.rul.note}</Note>
            {o.forecast.available && (
              <>
                <h3>Next 24 hours</h3>
                <LineChart xLabel="hours ahead" yLabel="°C"
                  series={[
                    { name: "Hot spot", x: o.forecast.t.map((_, i) => i), y: o.forecast.hot_spot_C, cls: "twin" },
                    { name: "Top oil", x: o.forecast.t.map((_, i) => i), y: o.forecast.top_oil_C, cls: "ink", dash: true },
                  ]} />
                <Note>Peak hot spot {num(o.forecast.peak_hot_spot_C)} °C. {o.forecast.method} Band: {o.forecast.band_basis}.</Note>
              </>
            )}
          </>
        )}
      </Section>
    </>
  );
}

// ---------------------------------------------------------------- Report
function ReportTab({ dataset, snapshot }: { dataset: string; snapshot: boolean }) {
  const frame = useRef<HTMLIFrameElement>(null);
  return (
    <Section title="Report" code="W-12">
      <div className="wb-row">
        <a className="wb-btn on" href={reportHref(dataset, "html")} target="_blank" rel="noreferrer">Open report</a>
        <a className="wb-btn" href={reportHref(dataset, "html", true)}>Download HTML</a>
        <button className="wb-btn" onClick={() => frame.current?.contentWindow?.print()}>Print or save as PDF</button>
        <a className="wb-btn" href={reportHref(dataset, "csv")}>Time series (CSV)</a>
        <a className="wb-btn" href={reportHref(dataset, "json")}>Everything (JSON)</a>
      </div>
      <Note>The HTML report is one self-contained page: charts are inline and nothing loads from the internet. The CSV has every sample with the health index, residual and alert flags; the JSON adds the asset, analysis, outlook and data-quality report.</Note>
      {!snapshot && <iframe ref={frame} className="wb-frame" title="Report preview" src={reportHref(dataset, "html")} />}
    </Section>
  );
}

// ---------------------------------------------------------------- Self-test
function SelfTestTab({ active }: { active: boolean }) {
  const q = useSelfTest(active);
  const sections = new Map<string, Record<string, unknown>[]>();
  (q.data?.rows ?? []).forEach((r) => { const k = String((r as Record<string, unknown>).section); sections.set(k, [...(sections.get(k) ?? []), r as Record<string, unknown>]); });
  const cols = (q.data?.columns ?? []).filter((c) => c !== "section");
  const LABEL: Record<string, string> = { measurement: "Measurement accuracy", trip: "Trip tests", oil: "Oil channel", status: "Status message" };
  return (
    <>
      <Note>CPRI's acceptance-test format: reference value against software value, pass at 1 % or better. The 50 A and 60 °C trip values are bench setpoints from the organisers' sheet, not operating alarms.</Note>
      {q.isError && <Note err>{(q.error as Error).message}</Note>}
      {[...sections.entries()].map(([s, rows], n) => (
        <Section key={s} title={LABEL[s] ?? s} code={`W-${13 + n}`}>
          <table className="wb-table">
            <thead><tr>{cols.map((c) => <th key={c}>{c.replace(/_/g, " ")}</th>)}</tr></thead>
            <tbody>{rows.map((r, i) => (
              <tr key={i}>{cols.map((c) => {
                const v = r[c];
                return <td key={c} className={c === "pass" ? (v === true ? "ok" : v === false ? "bad" : "") : typeof v === "number" ? "num" : ""}>
                  {c === "pass" ? (v === true ? "Pass" : v === false ? "Fail" : "—") : v == null ? "—" : String(v)}</td>;
              })}</tr>
            ))}</tbody>
          </table>
        </Section>
      ))}
    </>
  );
}

// ---------------------------------------------------------------- the overlay
export function Workbench({ dataset, time, timeSeries, snapshot, onClose, onSimulated }: {
  dataset: string; time: string | null; timeSeries: boolean; snapshot: boolean; onClose: () => void; onSimulated: (id: string) => void;
}) {
  const [tab, setTab] = useState<WbTab>("profile");
  const profile = useProfileState();
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="wb" role="dialog" aria-label="Workbench">
      <header className="wb-head">
        <nav className="tabs" aria-label="Workbench sections">
          {TABS.map((t) => (
            <button key={t.id} className={`tab${tab === t.id ? " on" : ""}`} aria-pressed={tab === t.id} onClick={() => setTab(t.id)}>
              <span className="tab-label">{t.label}</span><span className="tab-hint">{t.hint}</span>
            </button>
          ))}
        </nav>
        <span className="wb-ds">Dataset {dataset}</span>
        <button className="wb-close" onClick={onClose}>Back to the twin</button>
      </header>
      <div className="wb-scroll">
        {tab === "profile" && <ProfileTab p={profile} onSimulated={onSimulated} />}
        {tab === "physics" && <PhysicsTab p={profile} />}
        {tab === "outlook" && <OutlookTab dataset={dataset} t={time} timeSeries={timeSeries} />}
        {tab === "anomaly" && <Section title="Anomaly tests" code="W-12"><AnomalyTests /></Section>}
        {tab === "report" && <ReportTab dataset={dataset} snapshot={snapshot} />}
        {tab === "selftest" && <SelfTestTab active />}
      </div>
    </div>
  );
}
