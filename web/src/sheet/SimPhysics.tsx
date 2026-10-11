// SIMULATE: the physics behind the answer, live. Left: the IEC 60076-7 calculation chain with this run's numbers
// substituted (the model parameters come from the backend's what-if answer). Middle: the same first-order thermal
// equations integrated in real time from the start state, so you watch the oil and the winding warm toward steady
// state. Right: the heat balance (what the oil stores while it warms) and the paper ageing that accumulates.
import { useEffect, useRef, useState } from "react";
import type { WhatIf, WhatIfInput } from "../api/client";

type P = { P0_W: number; Pk_W: number; R: number; d_theta_or_K: number; x: number; y: number; gr_K: number; H: number; tau_oil_min: number; tau_winding_min: number; beta_bottom: number };
const f = (v: number, d = 1) => v.toFixed(d);
const ageing = (hs: number) => 2 ** ((hs - 98) / 6); // IEC 60076-7 (non-upgraded paper): relative rate, 1 at 98 °C

/** One line of the chain: what it is, the equation, the numbers put in, the answer. */
function Step({ n, name, eq, sub, out, unit }: { n: number; name: string; eq: string; sub: string; out: string; unit: string }) {
  return (
    <li className="calc-step">
      <span className="ph-n">{n}</span>
      <span className="ph-name">{name}</span>
      <b className="ph-out">{out}<small>{unit}</small></b>
      <code className="ph-eq">{eq}</code>
      <code className="ph-sub">= {sub}</code>
    </li>
  );
}

function Chain({ w, p, inp }: { w: WhatIf; p: P; inp: WhatIfInput }) {
  const K = w.load_pu, k = w.cooling;
  const rise_nom = p.d_theta_or_K * ((1 + p.R * K * K) / (1 + p.R)) ** p.x;
  return (
    <ol className="ph-chain">
      <Step n={1} name="Losses" eq="P = P₀ + K²·Pk" sub={`${f(p.P0_W, 0)} + ${f(K, 2)}²·${f(p.Pk_W, 0)}`} out={f(w.losses_total_W, 0)} unit=" W" />
      <Step n={2} name="Oil rise, design cooling" eq="Δθor·((1+R·K²)/(1+R))ˣ" sub={`${f(p.d_theta_or_K, 0)}·((1+${f(p.R, 1)}·${f(K * K, 2)})/${f(1 + p.R, 1)})^${f(p.x, 2)}`} out={f(rise_nom)} unit=" K" />
      <Step n={3} name="Cooling" eq="× k^(−x)" sub={`${f(rise_nom)} × ${f(k, 2)}^(−${f(p.x, 2)})`} out={f(w.top_oil_C - w.ambient_C)} unit=" K" />
      <Step n={4} name="Top oil" eq="θo = θa + Δθo" sub={`${f(w.ambient_C)} + ${f(w.top_oil_C - w.ambient_C)}`} out={f(w.top_oil_C)} unit=" °C" />
      <Step n={5} name="Winding gradient" eq="H·gr·Kʸ" sub={`${f(p.H, 1)}·${f(p.gr_K, 0)}·${f(K, 2)}^${f(p.y, 1)}`} out={f(w.winding_gradient_K)} unit=" K" />
      <Step n={6} name="Hot spot" eq="θh = θo + H·gr·Kʸ" sub={`${f(w.top_oil_C)} + ${f(w.winding_gradient_K)}`} out={f(w.hot_spot_C)} unit=" °C" />
      <Step n={7} name="Paper ageing" eq="V = 2^((θh − 98)/6)" sub={`2^((${f(w.hot_spot_C)} − 98)/6)`} out={w.ageing_rate >= 100 ? f(w.ageing_rate, 0) : f(w.ageing_rate, 2)} unit=" × normal" />
      <Step n={8} name="Approach" eq="θ(t) = θss + (θ₀ − θss)·e^(−t/τ)" sub={`τo ${f(p.tau_oil_min, 0)} min, τw ${f(p.tau_winding_min, 0)} min`} out={w.time_to_steady_min < 1 ? "0" : f(w.time_to_steady_min / 60)} unit=" h to settle" />
      <li className="ph-note">Plant at {f(inp.voltage, 2)} pu, PF {f(inp.pf, 2)}, {f(inp.unbalance, 1)} % unbalance feeds the what-if day behind the health index; the chain above is the thermal core.</li>
    </ol>
  );
}

const SPEEDS: [number, string][] = [[30, "30 min/s"], [120, "2 h/s"], [600, "10 h/s"]];
type Live = { t: number; top: number; grad: number; life: number; pts: [number, number, number][] };

/** Integrates the two first-order lags in real time: exact step of dθ/dt = (θss − θ)/τ each frame. */
function useIntegrator(w: WhatIf, p: P) {
  const [speed, setSpeed] = useState(120);
  const [run, setRun] = useState(0);
  const [, setTick] = useState(0);
  const st = useRef<Live>({ t: 0, top: w.start.top_oil_C, grad: w.start.gradient_K, life: 0, pts: [] });
  const key = `${w.top_oil_C}|${w.hot_spot_C}|${w.start.top_oil_C}|${w.start.gradient_K}|${p.tau_oil_min}|${run}`;
  useEffect(() => {
    st.current = { t: 0, top: w.start.top_oil_C, grad: w.start.gradient_K, life: 0, pts: [] };
    let last = performance.now(), raf = 0;
    const loop = (now: number) => {
      const s = st.current;
      const dtMin = Math.min(0.1, (now - last) / 1000) * speed; // simulated minutes this frame
      last = now;
      if (s.t < 8 * p.tau_oil_min) {
        s.top += (w.top_oil_C - s.top) * (1 - Math.exp(-dtMin / p.tau_oil_min));
        s.grad += (w.winding_gradient_K - s.grad) * (1 - Math.exp(-dtMin / p.tau_winding_min));
        s.t += dtMin;
        s.life += (ageing(s.top + s.grad) * dtMin) / 60;
        s.pts.push([s.t, s.top, s.top + s.grad]);
        setTick((n) => n + 1);
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [key, speed]); // eslint-disable-line react-hooks/exhaustive-deps
  return { s: st.current, speed, setSpeed, restart: () => setRun((n) => n + 1), done: st.current.t >= 8 * p.tau_oil_min };
}
type Integ = ReturnType<typeof useIntegrator>;

function LiveScope({ w, p, it }: { w: WhatIf; p: P; it: Integ }) {
  const { s } = it;
  const tEnd = Math.max(4 * p.tau_oil_min, w.time_to_steady_min * 1.1);
  const vals = [...s.pts.flatMap((q) => [q[1], q[2]]), w.hot_spot_C, w.top_oil_C, w.start.top_oil_C, w.ambient_C];
  const lo = Math.floor(Math.min(...vals) / 10) * 10, hi = Math.ceil(Math.max(...vals) / 10) * 10 || lo + 10;
  const W = 360, H = 120, L = 28, R = 6, T = 6, B = 14;
  const x = (t: number) => L + (t / tEnd) * (W - L - R), y = (v: number) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const path = (i: 1 | 2) => s.pts.filter((_, n) => n % 2 === 0).map((q, n) => `${n ? "L" : "M"}${x(q[0]).toFixed(1)} ${y(q[i]).toFixed(1)}`).join("");
  const hs = s.top + s.grad, rise = s.top - w.ambient_C, riseSS = w.top_oil_C - w.ambient_C;
  return (
    <div className="ph-live">
      <svg viewBox={`0 0 ${W} ${H}`} className="ph-scope" role="img" aria-label="Live integration of top-oil and hot-spot temperature">
        {[lo, (lo + hi) / 2, hi].map((v) => <g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className="g" /><text x={L - 3} y={y(v) + 3} textAnchor="end">{f(v, 0)}</text></g>)}
        <line x1={L} x2={W - R} y1={y(w.hot_spot_C)} y2={y(w.hot_spot_C)} className="ss" />
        <line x1={L} x2={W - R} y1={y(w.top_oil_C)} y2={y(w.top_oil_C)} className="ss" />
        <path d={path(2)} className="hs" /><path d={path(1)} className="top" />
        {s.pts.length > 0 && <><circle cx={x(s.t)} cy={y(hs)} r={3} className="hs-dot" /><circle cx={x(s.t)} cy={y(s.top)} r={3} className="top-dot" /></>}
        <text x={L} y={H - 2}>0</text><text x={W - R} y={H - 2} textAnchor="end">{f(tEnd / 60, 0)} h</text>
      </svg>
      <div className="ph-readout">
        <span>t <b>{f(s.t / 60, 2)}</b> h</span>
        <span>θo <b>{f(s.top)}</b> °C</span>
        <span>θh <b>{f(hs)}</b> °C</span>
        <span>of the oil rise <b>{riseSS > 0 ? f((rise / riseSS) * 100, 0) : "100"}</b> %</span>
      </div>
      <div className="ph-ctl">
        {SPEEDS.map(([v, l]) => <button key={v} className={it.speed === v ? "on" : ""} onClick={() => it.setSpeed(v)}>{l}</button>)}
        <button onClick={it.restart}>{it.done ? "Run again" : "Restart"}</button>
      </div>
    </div>
  );
}

/** Heat balance of the oil while it warms (stored = P·(1 − Δθ/Δθss) for a first-order lag) and the paper life used so far. */
function Balance({ w, it }: { w: WhatIf; it: Integ }) {
  const riseSS = w.top_oil_C - w.ambient_C;
  const frac = riseSS > 0 ? Math.min(1, Math.max(0, (it.s.top - w.ambient_C) / riseSS)) : 1;
  const P = w.losses_total_W, stored = P * (1 - frac), out = P - stored;
  const days = it.s.life / 24;
  const v = ageing(it.s.top + it.s.grad);
  return (
    <div className="ph-bal">
      <div className="ph-bar"><span>Heat made in the windings and core</span><b>{f(P / 1000, 2)} kW</b><u><s style={{ width: "100%", background: "var(--measured)" }} /></u></div>
      <div className="ph-bar"><span>Leaving through the radiators</span><b>{f(out / 1000, 2)} kW</b><u><s style={{ width: `${(out / P) * 100}%`, background: "var(--twin)" }} /></u></div>
      <div className="ph-bar"><span>Stored, warming the oil</span><b>{f(stored / 1000, 2)} kW</b><u><s style={{ width: `${(stored / P) * 100}%`, background: "var(--ink)" }} /></u></div>
      <p className="ph-foot">Made = leaving + stored. As the oil nears its steady temperature storage falls to zero.</p>
      <p className="ph-life">Paper life used since the run began: <b>{days < 0.01 ? f(it.s.life, 2) + " h" : f(days, 3) + " days"}</b> (at {f(v, v >= 100 ? 0 : 2)} × normal now)</p>
    </div>
  );
}

/** Load (pu) at which the hot spot reaches `limit` °C at this ambient and cooling: bisection on the same equations as the chain. */
function loadAt(limit: number, w: WhatIf, p: P): number | null {
  const k = Math.min(1.5, Math.max(0.05, w.cooling));
  const hs = (K: number) => w.ambient_C + p.d_theta_or_K * ((1 + p.R * K * K) / (1 + p.R)) ** p.x * k ** -p.x + p.H * p.gr_K * K ** p.y;
  if (hs(0.05) > limit) return null;
  if (hs(2.5) < limit) return 2.5;
  let lo = 0.05, hi = 2.5;
  for (let n = 0; n < 40; n++) { const m = (lo + hi) / 2; if (hs(m) < limit) lo = m; else hi = m; }
  return lo;
}

function Headroom({ w }: { w: WhatIf }) {
  const p = w.params as unknown as P;
  const rows: [string, number, number | null][] = [["Wear stays at the normal rate", 98, loadAt(98, w, p)], ["Continuous limit", 110, loadAt(110, w, p)], ["Short-time limit", 140, loadAt(140, w, p)]];
  const K = w.load_pu;
  return (
    <div className="ph-head">
      {rows.map(([name, lim, k]) => (
        <div key={name} className="ph-hr">
          <span>{name} <small>{lim} °C hot spot</small></span>
          <b className={k != null && K > k ? "over" : ""}>{k == null ? "never" : f(k, 2) + " pu"}</b>
          <u><s style={{ width: `${Math.min(100, ((k ?? 0) / 1.6) * 100)}%` }} /><i style={{ left: `${Math.min(100, (K / 1.6) * 100)}%` }} /></u>
        </div>
      ))}
      <p className="ph-foot">Highest load this transformer can carry at {f(w.ambient_C, 0)} °C ambient and {f(w.cooling * 100, 0)} % cooling before the hot spot reaches each limit. The tick is your load now ({f(K, 2)} pu).</p>
    </div>
  );
}

const PRESETS: [string, string, Partial<WhatIfInput>][] = [
  ["Normal day", "load 0.6, 25 °C", { load: 0.6, ambient: 25, cooling: 1, voltage: 1, pf: 0.95, unbalance: 0 }],
  ["Summer peak", "load 1.0, 42 °C", { load: 1.0, ambient: 42, cooling: 1, voltage: 1, pf: 0.92, unbalance: 2 }],
  ["Overload", "load 1.3", { load: 1.3, ambient: 35, cooling: 1, voltage: 1, pf: 0.9, unbalance: 3 }],
  ["Cooling failure", "radiators at 50 %", { load: 0.9, ambient: 35, cooling: 0.5, voltage: 1, pf: 0.95, unbalance: 0 }],
  ["Voltage sag", "0.9 pu, low PF", { load: 0.9, ambient: 30, cooling: 1, voltage: 0.9, pf: 0.8, unbalance: 0 }],
  ["Unbalanced", "one phase heavy", { load: 0.8, ambient: 30, cooling: 1, voltage: 1, pf: 0.95, unbalance: 18 }],
];
/** Scenario chips over the model: one click sets all six rulers. */
export function SimPresets({ inp, onChange }: { inp: WhatIfInput; onChange: (i: WhatIfInput) => void }) {
  return (
    <div className="sim-presets" role="group" aria-label="Scenarios">
      {PRESETS.map(([name, hint, v]) => (
        <button key={name} title={hint} onClick={() => onChange({ ...inp, ...v })}>{name}</button>
      ))}
    </div>
  );
}

/** The calculation chain with this run's numbers, in the right-hand panel (it replaces the heat balance and the life clock in Simulate). */
export function SimCalc({ w, inp }: { w: WhatIf | undefined; inp: WhatIfInput | null }) {
  if (!w || !inp) return null;
  const p = w.params as unknown as P;
  return (
    <section className="side-calc" aria-label="The physics behind this simulation">
      <h3>Physics, calculated live <small>IEC 60076-7</small></h3>
      <Chain w={w} p={p} inp={inp} />
    </section>
  );
}

export function SimPhysics({ w, inp }: { w: WhatIf | undefined; inp: WhatIfInput | null }) {
  if (!w || !inp) return null;
  return <SimPhysicsBody w={w} />;
}
function SimPhysicsBody({ w }: { w: WhatIf }) {
  const p = w.params as unknown as P;
  const it = useIntegrator(w, p);
  return (
    <section className="st-trends st-physics" aria-label="Warming, heat balance and headroom">
      <div className="st-card ph-card"><h3>Warming up, integrated live</h3><LiveScope w={w} p={p} it={it} /></div>
      <div className="st-card ph-card"><h3>Heat balance and ageing</h3><Balance w={w} it={it} /></div>
      <div className="st-card ph-card"><h3>Load headroom</h3><Headroom w={w} /></div>
    </section>
  );
}
