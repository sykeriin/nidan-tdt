// SIMULATE mode. Three drawn rulers (load, ambient, cooling) ask GET /api/whatif for the steady state; the
// answer is loaded into the replay clock as a one-row frame, so every layer (temperature field, oil flow,
// heat arrows, thermometer, heat balance, life clock) shows the simulated state with the same bindings.
// The strip shows the steady-state readout and the approach curve from the twin's state at the replay cursor.
import type { Frames } from "../player/player";
import type { WhatIf, WhatIfInput } from "../api/client";

/** Backend what-if answer → the frame columns the views already read (renaming only, see BINDINGS.md). */
export function whatIfFrames(w: WhatIf, dataset: string): Frames {
  const c: Record<string, number | string> = {
    load_pu: w.load_pu, amb_C: w.ambient_C, IR: w.current_A, IY: w.current_A, IB: w.current_A,
    twin_oil_C: w.top_oil_C, twin_hs_C: w.hot_spot_C, hs_ageing_C: w.hot_spot_C, ageing_source: "twin",
    bottom_oil_C: w.bottom_oil_C, avg_winding_C: w.avg_winding_C, hs_gradient_K: w.winding_gradient_K,
    top_oil_ss_C: w.top_oil_C, hot_spot_ss_C: w.hot_spot_C, hot_spot_factor: w.hot_spot_factor,
    losses_noload_W: w.losses_noload_W, losses_load_W: w.losses_load_W, losses_total_W: w.losses_total_W,
    heat_dissipated_W: w.heat_dissipated_W, heat_stored_W: w.heat_stored_W,
    oil_flow_intensity: w.oil_flow_intensity, radiator_effectiveness: w.radiator_effectiveness,
    tau_oil_min: w.tau_oil_min, tau_winding_min: w.tau_winding_min,
    // life clock in Simulate: life used per day at this state; expected = radiators as designed
    aging_rate: w.ageing_rate_nominal_cooling, aging_rate_actual: w.ageing_rate,
    days_aged_cum: w.ageing_rate_nominal_cooling, days_aged_actual_cum: w.ageing_rate,
  };
  const now = new Date().toISOString();
  return { dataset: `${dataset}#sim`, t: [Date.now()], iso: [now], cols: Object.fromEntries(Object.entries(c).map(([k, v]) => [k, [v]])) };
}

const RULERS: { key: keyof WhatIfInput; label: string; min: number; max: number; step: number; unit: string; ticks: number[]; fmt: (v: number) => string }[] = [
  { key: "load", label: "Load", min: 0.3, max: 1.4, step: 0.01, unit: "pu", ticks: [0.3, 0.5, 0.75, 1, 1.25, 1.4], fmt: (v) => v.toFixed(2) },
  { key: "ambient", label: "Ambient", min: 15, max: 50, step: 0.5, unit: "°C", ticks: [15, 20, 30, 40, 50], fmt: (v) => v.toFixed(1) },
  { key: "cooling", label: "Cooling", min: 0.5, max: 1, step: 0.01, unit: "%", ticks: [0.5, 0.6, 0.7, 0.8, 0.9, 1], fmt: (v) => (v * 100).toFixed(0) },
];

const dur = (min: number) => (min < 1 ? "already there" : min < 90 ? `${min.toFixed(0)} min` : `${Math.floor(min / 60)} h ${String(Math.round(min % 60)).padStart(2, "0")} min`);
const rate = (v: number) => (v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2));

export function SimControls({ inp, onChange, w, busy, error }: {
  inp: WhatIfInput; onChange: (i: WhatIfInput) => void; w: WhatIf | undefined; busy: boolean; error: string | null;
}) {
  return (
    <div className="sim">
      <div className="sim-rulers">
        {RULERS.map((r) => {
          const v = inp[r.key];
          const pos = (x: number) => `${((x - r.min) / (r.max - r.min)) * 100}%`;
          return (
            <label key={r.key} className="sim-ruler">
              <span className="sr-label">{r.label}</span>
              <span className="sr-track">
                {r.ticks.map((t) => <span key={t} className="sr-tick" style={{ left: pos(t) }}><i>{r.fmt(t)}</i></span>)}
                <input type="range" min={r.min} max={r.max} step={r.step} value={v} aria-label={`${r.label}, ${r.unit}`}
                  onChange={(e) => onChange({ ...inp, [r.key]: Number(e.target.value) })} />
              </span>
              <span className="sr-value"><b>{r.fmt(v)}</b> {r.unit}{r.key === "load" && w ? <em> {w.current_A.toFixed(0)} A</em> : null}</span>
            </label>
          );
        })}
      </div>
      <div className="sim-out">
        {error ? <p className="field-error">{error}</p> : !w ? <p className="field-note">Asking the twin…</p> : <>
          <table className="sim-read">
            <tbody>
              <tr><th scope="row">steady hot-spot</th><td className="t">{w.hot_spot_C.toFixed(1)} °C</td></tr>
              <tr><th scope="row">steady top-oil</th><td className="t">{w.top_oil_C.toFixed(1)} °C</td></tr>
              <tr><th scope="row">paper ageing</th><td className="t">{rate(w.ageing_rate)} × normal</td></tr>
              <tr><th scope="row">reaches it in</th><td className="t">{dur(w.time_to_steady_min)}</td></tr>
              <tr><td colSpan={2} className="dim">{inp.cooling < 1
                ? `full cooling: ${w.hot_spot_nominal_cooling_C.toFixed(1)} °C, ${rate(w.ageing_rate_nominal_cooling)} ×`
                : "radiators as designed"}; from {w.start.from}</td></tr>
            </tbody>
          </table>
          <Approach w={w} />
        </>}
        {busy && <span className="sim-busy" aria-live="polite">…</span>}
      </div>
    </div>
  );
}

function Approach({ w }: { w: WhatIf }) {
  const Wd = 250, Hd = 96, L = 4, R = 54, T = 12, B = 14;
  const c = w.curve;
  const tMax = c.t_min[c.t_min.length - 1] || 1;
  const all = [...c.top_oil_C, ...c.hot_spot_C];
  const lo = Math.floor(Math.min(...all) / 10) * 10, hi = Math.ceil(Math.max(...all) / 10) * 10 || lo + 10;
  const x = (t: number) => L + (t / tMax) * (Wd - L - R);
  const y = (v: number) => T + (1 - (v - lo) / (hi - lo || 1)) * (Hd - T - B);
  const path = (vals: number[]) => vals.map((v, k) => `${k ? "L" : "M"}${x(c.t_min[k]).toFixed(1)} ${y(v).toFixed(1)}`).join("");
  const xs = x(Math.min(w.time_to_steady_min, tMax));
  return (
    <figure className="approach" aria-label="Approach to steady state">
      <svg width={Wd} height={Hd} aria-hidden="true">
        <line x1={L} x2={Wd - R} y1={y(w.hot_spot_C)} y2={y(w.hot_spot_C)} className="ss" />
        <line x1={L} x2={Wd - R} y1={y(w.top_oil_C)} y2={y(w.top_oil_C)} className="ss" />
        <path d={path(c.hot_spot_C)} className="tw" />
        <path d={path(c.top_oil_C)} className="tw" />
        <text x={Wd - R + 4} y={y(w.hot_spot_C) + 3}>hot-spot</text>
        <text x={Wd - R + 4} y={y(w.top_oil_C) + 3}>top-oil</text>
        <g className="tau"><line x1={L} x2={x(w.tau_oil_min)} y1={Hd - 5} y2={Hd - 5} />
          <line x1={x(w.tau_oil_min)} x2={x(w.tau_oil_min)} y1={Hd - 9} y2={Hd - 1} />
          <text x={x(w.tau_oil_min) + 3} y={Hd - 2}>τo {w.tau_oil_min.toFixed(0)} min</text></g>
        {w.time_to_steady_min > 1 && <g className="settle"><line x1={xs} x2={xs} y1={T - 6} y2={Hd - B} />
          <text x={xs} y={T - 2} textAnchor="middle">steady</text></g>}
        <text x={L} y={T - 2} className="axl">{hi} °C</text>
      </svg>
      <figcaption>Approach to steady state, {(tMax / 60).toFixed(0)} h shown</figcaption>
    </figure>
  );
}

export function SimInputs({ w }: { w: WhatIf | undefined }) {
  const rows: [string, string, string][] = w ? [
    ["Load factor K", w.load_pu.toFixed(2), "pu"], ["Phase current", w.current_A.toFixed(0), "A"],
    ["Ambient", w.ambient_C.toFixed(1), "°C"], ["Cooling", (w.cooling * 100).toFixed(0), "% of design"],
  ] : [];
  return (
    <section className="schedule" aria-label="Simulation inputs">
      <header className="schedule-head"><h2>Simulation in</h2><span className="code">Schedule 1</span></header>
      <table><tbody>
        {rows.map(([l, v, u]) => <tr key={l} className="k-twin"><th scope="row">{l}</th><td className="num">{v}</td><td className="unit">{u}</td><td className="trust" /></tr>)}
      </tbody></table>
      <p className="sim-note">Steady state of the twin at these conditions: what the transformer would settle to, not measured data. Set by the rulers below.</p>
    </section>
  );
}
