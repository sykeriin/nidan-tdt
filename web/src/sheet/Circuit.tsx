// CIRCUIT: the electrical side of the digital twin, drawn live. One-line diagram (grid, HV breaker, transformer, LV
// breaker, load) with current flowing along the wires; the per-phase equivalent circuit with its parameters; the
// phasor diagram; the three-phase waveforms; and the power triangle. All numbers come from the replay row (measured V, I,
// PF, frequency) and the nameplate (rating, voltages, losses). Impedance voltage is not in the data: 5 % is assumed.
import { useEffect, useRef, useState } from "react";
import { player, usePlayerIndex } from "../player/player";

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const UK = 0.05; // assumed impedance voltage (typical 4 to 6 % for 1 MVA distribution units)
const I0 = 0.01; // assumed no-load current, per unit
const C = { hv: "#2457A6", lv: "#D9480F", ink: "#1B1B18", mute: "#8C8A80", ok: "#3B7A3E" };

function useClock() {
  const [a, setA] = useState(0);
  const r = useRef(0);
  useEffect(() => {
    let last = performance.now(), raf = 0;
    const loop = (now: number) => { r.current = (r.current + (now - last) / 1000 * 1.1) % (Math.PI * 2); last = now; setA(r.current); raf = requestAnimationFrame(loop); };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);
  return a;
}
const f = (v: number | null, d = 1) => (v == null ? "—" : v.toFixed(d));

export function Circuit({ asset, onClose }: { asset: Record<string, unknown> | null; onClose: () => void }) {
  const i = usePlayerIndex();
  const r = i >= 0 ? player.row(i) : {};
  const ang = useClock();
  const Ir = num(asset?.i_rated_A) ?? 1391, Sn = num(asset?.rating_kVA) ?? 1000;
  const Vn = num(asset?.lv_voltage_V) ?? 415, Vhv = num(asset?.hv_voltage_V) ?? 11000;
  const Pk = num(asset?.load_loss_W) ?? 10000, P0 = num(asset?.no_load_loss_W) ?? 1100;
  const Iph = ["IR", "IY", "IB"].map((k) => num(r[k])), Vph = ["VR", "VY", "VB"].map((k) => num(r[k]));
  const ok = Iph.every((x) => x != null) && Vph.every((x) => x != null);
  const I = ok ? (Iph as number[]).reduce((a, b) => a + b, 0) / 3 : 0, V = ok ? (Vph as number[]).reduce((a, b) => a + b, 0) / 3 : Vn / Math.sqrt(3);
  const pf = Math.min(1, Math.max(0.05, num(r.PF) ?? 0.95)), phi = Math.acos(pf), hz = num(r.freq_Hz) ?? 50;
  const S = (3 * V * I) / 1000, P = S * pf, Q = S * Math.sin(phi);
  const Vbase = Vn / Math.sqrt(3), Zb = Vbase / Ir;
  const ur = Pk / (Sn * 1000), ux = Math.sqrt(UK * UK - ur * ur);
  const Req = ur * Zb, Xeq = ux * Zb;
  const Ic = P0 / (3 * Vbase), I0a = I0 * Ir, Im = Math.sqrt(Math.max(0, I0a * I0a - Ic * Ic));
  const Rc = Vbase * Vbase / (P0 / 3), Xm = Vbase / (Im || 1);
  const dV = I * (Req * pf + Xeq * Math.sin(phi)), reg = (dV / V) * 100;
  const Ex = V + dV, Ey = I * (Xeq * pf - Req * Math.sin(phi));
  const cu = 3 * I * I * Req, core = P0 * (V / Vbase) ** 2, eff = P > 0 ? (P * 1000 / (P * 1000 + cu + core)) * 100 : 0;
  const Ihv = (I * Vn) / Vhv, K = Ir ? I / Ir : 0;
  const speed = 0.25 + 0.9 * Math.min(1.4, K);

  // wires: dots running along a path, as many as fit
  const Flow = ({ d, color, n = 7, rev = false }: { d: string; color: string; n?: number; rev?: boolean }) => {
    const id = useRef(`p${Math.random().toString(36).slice(2, 8)}`).current;
    return (
      <g>
        <path id={id} d={d} fill="none" stroke={color} strokeWidth={2.2} opacity={0.35} />
        {Array.from({ length: n }, (_, k) => (
          <circle key={k} r={3.3} fill={color}>
            <animateMotion dur={`${(5 / speed).toFixed(2)}s`} repeatCount="indefinite" begin={`${-(k * 5) / speed / n}s`} keyPoints={rev ? "1;0" : "0;1"} keyTimes="0;1" calcMode="linear"><mpath href={`#${id}`} /></animateMotion>
          </circle>
        ))}
      </g>
    );
  };

  // waveforms: one cycle shown, phase-shifted by the clock
  const wave = (k: number, amp: number, lag: number) => {
    const W = 300, H = 90, pts: string[] = [];
    for (let x = 0; x <= W; x += 3) { const th = (x / W) * Math.PI * 4 - ang * 2 - (k * 2 * Math.PI) / 3 - lag; pts.push(`${x ? "L" : "M"}${x} ${(H / 2 - Math.sin(th) * amp).toFixed(1)}`); }
    return pts.join("");
  };
  const ph = [0, 1, 2], phc = ["#D9480F", "#C9A000", "#2457A6"];
  const cx = 120, cy = 130;

  return (
    <div className="circuit" role="dialog" aria-label="Electrical circuit">
      <header className="ck-head">
        <h2>Electrical circuit <span>live from the replay clock</span></h2>
        <button className="unpin" onClick={onClose} aria-label="Close circuit page">×</button>
      </header>
      <div className="ck-body">
        <section className="ck-card ck-sld">
          <h3>One-line diagram</h3>
          <svg viewBox="0 0 1180 215" className="ck-svg ck-sld-svg" role="img" aria-label="One-line diagram">
            {/* grid */}
            <g transform="translate(30,70)"><circle cx="30" cy="35" r="26" fill="none" stroke={C.ink} strokeWidth="2" /><path d="M14 35 q8 -14 16 0 t16 0" fill="none" stroke={C.hv} strokeWidth="2.4" /><text x="30" y="82" textAnchor="middle" className="t b">Grid</text><text x="30" y="97" textAnchor="middle" className="t m">{(Vhv / 1000).toFixed(0)} kV, {hz.toFixed(2)} Hz</text></g>
            <Flow d="M120 105 H 300" color={C.hv} />
            {/* HV breaker */}
            <g transform="translate(300,90)"><rect width="30" height="30" fill="#fff" stroke={C.ink} strokeWidth="2" /><path d="M5 25 L25 5" stroke={C.ink} strokeWidth="2.4" /><text x="15" y="52" textAnchor="middle" className="t m">HV breaker</text><text x="15" y="66" textAnchor="middle" className="t ok">closed</text></g>
            <Flow d="M330 105 H 480" color={C.hv} n={5} />
            <text x="405" y="92" textAnchor="middle" className="t v">{f(Ihv, 1)} A</text>
            {/* transformer */}
            <g transform="translate(480,40)">
              <circle cx="70" cy="65" r="48" fill="#fff" stroke={C.hv} strokeWidth="3" /><circle cx="130" cy="65" r="48" fill="#fff" stroke={C.lv} strokeWidth="3" opacity="0.92" />
              <text x="100" y="132" textAnchor="middle" className="t b">Transformer-1</text><text x="100" y="147" textAnchor="middle" className="t m">{Sn} kVA · Dyn11 · {(Vhv / 1000).toFixed(0)} / {(Vn / 1000).toFixed(3)} kV</text>
              <text x="70" y="62" textAnchor="middle" className="t big" fill={C.hv}>HV</text><text x="130" y="62" textAnchor="middle" className="t big" fill={C.lv}>LV</text>
              <text x="100" y="82" textAnchor="middle" className="t m">{f(K * 100, 0)} % load</text>
            </g>
            <Flow d="M680 105 H 840" color={C.lv} n={8} />
            <text x="760" y="92" textAnchor="middle" className="t v">{f(I, 0)} A</text>
            {/* LV breaker */}
            <g transform="translate(840,90)"><rect width="30" height="30" fill="#fff" stroke={C.ink} strokeWidth="2" /><path d="M5 25 L25 5" stroke={C.ink} strokeWidth="2.4" /><text x="15" y="52" textAnchor="middle" className="t m">LV breaker</text><text x="15" y="66" textAnchor="middle" className="t ok">closed</text></g>
            <Flow d="M870 105 H 1010" color={C.lv} n={5} />
            {/* load */}
            <g transform="translate(1010,70)"><rect width="130" height="70" rx="6" fill="#fff" stroke={C.ink} strokeWidth="2" /><text x="65" y="26" textAnchor="middle" className="t b">Campus load</text><text x="65" y="44" textAnchor="middle" className="t v">{f(P, 0)} kW</text><text x="65" y="60" textAnchor="middle" className="t m">{f(Q, 0)} kvar · PF {f(pf, 2)}</text></g>
            {/* meters */}
            <text x="410" y="170" textAnchor="middle" className="t m">HV side: {f(Ihv, 1)} A line, {(Vhv / 1000).toFixed(1)} kV</text>
            <text x="760" y="170" textAnchor="middle" className="t m">LV side: {f(V, 0)} V per phase, {f(V * Math.sqrt(3), 0)} V line</text>
            <text x="590" y="209" textAnchor="middle" className="t m">Losses now: core {f(core, 0)} W + copper {f(cu, 0)} W = {f(core + cu, 0)} W · efficiency {f(eff, 2)} %</text>
          </svg>
        </section>

        <section className="ck-card">
          <h3>Equivalent circuit, per phase <em>referred to the LV side</em></h3>
          <svg viewBox="0 0 420 210" className="ck-svg" role="img" aria-label="Per-phase equivalent circuit">
            <path d="M20 60 H80" stroke={C.ink} strokeWidth="2" fill="none" />
            <rect x="80" y="48" width="64" height="24" fill="#fff" stroke={C.ink} strokeWidth="2" /><text x="112" y="43" textAnchor="middle" className="t m">R<tspan baselineShift="sub" fontSize="8">eq</tspan> {f(Req * 1000, 2)} mΩ</text>
            <path d="M144 60 H175" stroke={C.ink} strokeWidth="2" fill="none" />
            <path d="M175 60 q6 -18 12 0 t12 0 t12 0 t12 0" stroke={C.ink} strokeWidth="2" fill="none" /><text x="205" y="43" textAnchor="middle" className="t m">X<tspan baselineShift="sub" fontSize="8">eq</tspan> {f(Xeq * 1000, 2)} mΩ</text>
            <path d="M247 60 H 330" stroke={C.ink} strokeWidth="2" fill="none" />
            {/* shunt branch */}
            <path d="M85 60 V 90 M85 90 H 60 M85 90 H110" stroke={C.ink} strokeWidth="2" fill="none" />
            <rect x="48" y="90" width="24" height="52" fill="#fff" stroke={C.ink} strokeWidth="2" /><text x="30" y="158" textAnchor="middle" className="t m">R<tspan baselineShift="sub" fontSize="8">c</tspan> {f(Rc, 0)} Ω</text>
            <path d="M98 90 V 100 q-12 4 0 8 t0 8 t0 8 t0 8" stroke={C.ink} strokeWidth="2" fill="none" /><text x="130" y="158" textAnchor="middle" className="t m">X<tspan baselineShift="sub" fontSize="8">m</tspan> {f(Xm, 0)} Ω</text>
            <path d="M60 142 V 170 H 98 V 148 M20 60 V 170 H 60 M98 170 H 330 V 60" stroke={C.ink} strokeWidth="2" fill="none" />
            <text x="12" y="118" textAnchor="middle" className="t v" transform="rotate(-90 12 118)">{f(Math.hypot(Ex, Ey), 0)} V (no-load)</text>
            <rect x="330" y="60" width="0" height="0" />
            <g transform="translate(330,60)"><rect x="-14" y="0" width="28" height="110" rx="4" fill="#FFF3EA" stroke={C.lv} strokeWidth="2" /><text x="0" y="60" textAnchor="middle" className="t b" fill={C.lv}>load</text></g>
            <text x="352" y="106" className="t v">{f(V, 1)} V</text><text x="352" y="122" className="t m">{f(I, 0)} A ∠ −{f((phi * 180) / Math.PI, 0)}°</text>
            <text x="20" y="196" className="t m">Impedance voltage assumed {UK * 100} %, no-load current assumed {I0 * 100} % (not in the data)</text>
          </svg>
        </section>

        <section className="ck-card">
          <h3>Phasors <em>rotating at {hz.toFixed(0)} Hz, slowed down</em></h3>
          <svg viewBox="0 0 260 210" className="ck-svg" role="img" aria-label="Phasor diagram">
            <circle cx={cx} cy={cy} r="78" fill="none" stroke="#ECEAE2" /><line x1={cx - 90} x2={cx + 90} y1={cy} y2={cy} stroke="#ECEAE2" /><line y1={cy - 90} y2={cy + 90} x1={cx} x2={cx} stroke="#ECEAE2" />
            {ph.map((k) => { const a = ang - (k * 2 * Math.PI) / 3; return <line key={"v" + k} x1={cx} y1={cy} x2={cx + 78 * Math.cos(a)} y2={cy - 78 * Math.sin(a)} stroke={phc[k]} strokeWidth="2.4" />; })}
            {ph.map((k) => { const a = ang - (k * 2 * Math.PI) / 3 - phi; return <line key={"i" + k} x1={cx} y1={cy} x2={cx + 52 * Math.cos(a)} y2={cy - 52 * Math.sin(a)} stroke={phc[k]} strokeWidth="2" strokeDasharray="4 3" />; })}
            {ph.map((k) => { const a = ang - (k * 2 * Math.PI) / 3; return <text key={"l" + k} x={cx + 90 * Math.cos(a)} y={cy - 90 * Math.sin(a) + 4} textAnchor="middle" className="t b" fill={phc[k]}>{"RYB"[k]}</text>; })}
            <text x="130" y="14" textAnchor="middle" className="t m">solid = voltage · dashed = current</text>
            <text x="130" y="198" textAnchor="middle" className="t v">I lags V by {f((phi * 180) / Math.PI, 1)}°, PF {f(pf, 2)}</text>
          </svg>
        </section>

        <section className="ck-card">
          <h3>Waveforms <em>voltage and current, three phases</em></h3>
          <svg viewBox="0 0 300 190" className="ck-svg" role="img" aria-label="Three-phase waveforms">
            <g><line x1="0" x2="300" y1="45" y2="45" stroke="#ECEAE2" />{ph.map((k) => <path key={"vw" + k} d={wave(k, 36, 0)} stroke={phc[k]} fill="none" strokeWidth="1.8" />)}<text x="4" y="10" className="t m">Voltage, {f(V * Math.SQRT2, 0)} V peak</text></g>
            <g transform="translate(0,95)"><line x1="0" x2="300" y1="45" y2="45" stroke="#ECEAE2" />{ph.map((k) => <path key={"iw" + k} d={wave(k, 36 * Math.min(1, K / 1.2 + 0.1), phi)} stroke={phc[k]} fill="none" strokeWidth="1.8" strokeDasharray="5 3" />)}<text x="4" y="10" className="t m">Current, {f(I * Math.SQRT2, 0)} A peak</text></g>
          </svg>
        </section>

        <section className="ck-card ck-power">
          <h3>Power</h3>
          <svg viewBox="0 0 220 150" className="ck-svg" role="img" aria-label="Power triangle">
            {(() => { const s = 110 / Math.max(S, 1); const px = 20 + P * s, py = 120 - Q * s; return <>
              <path d={`M20 120 H${px} L${px} ${py}Z`} fill="#FFF3EA" stroke={C.lv} strokeWidth="2" />
              <text x={(20 + px) / 2} y="138" textAnchor="middle" className="t v">P {f(P, 0)} kW</text>
              <text x={px + 6} y={(120 + py) / 2} className="t v">Q {f(Q, 0)} kvar</text>
              <text x={(20 + px) / 2 - 12} y={(120 + py) / 2 - 6} className="t b">S {f(S, 0)} kVA</text>
              <text x="26" y="112" className="t m">φ {f((phi * 180) / Math.PI, 0)}°</text></>; })()}
          </svg>
        </section>

        <section className="ck-card ck-calc">
          <h3>How it is calculated</h3>
          <table>
            <tbody>
              <tr><th>Apparent power</th><td>S = 3·V·I</td><td>3 × {f(V, 1)} × {f(I, 0)}</td><td className="o">{f(S, 0)} kVA</td></tr>
              <tr><th>Real / reactive</th><td>P = S·cosφ, Q = S·sinφ</td><td>{f(S, 0)} × {f(pf, 3)}</td><td className="o">{f(P, 0)} kW / {f(Q, 0)} kvar</td></tr>
              <tr><th>Series resistance</th><td>R = (P<sub>k</sub> / S<sub>n</sub>)·Z<sub>b</sub></td><td>({f(Pk, 0)} / {f(Sn * 1000, 0)}) × {f(Zb * 1000, 1)} mΩ</td><td className="o">{f(Req * 1000, 2)} mΩ</td></tr>
              <tr><th>Series reactance</th><td>X = √(u<sub>k</sub>² − u<sub>r</sub>²)·Z<sub>b</sub></td><td>√({UK}² − {f(ur, 4)}²) × {f(Zb * 1000, 1)} mΩ</td><td className="o">{f(Xeq * 1000, 2)} mΩ</td></tr>
              <tr><th>Voltage drop</th><td>ΔV = I(R·cosφ + X·sinφ)</td><td>{f(I, 0)} × ({f(Req * 1000, 2)}·{f(pf, 2)} + {f(Xeq * 1000, 2)}·{f(Math.sin(phi), 2)}) m</td><td className="o">{f(dV, 2)} V ({f(reg, 2)} %)</td></tr>
              <tr><th>Copper loss</th><td>3·I²·R</td><td>3 × {f(I, 0)}² × {f(Req * 1000, 2)} m</td><td className="o">{f(cu, 0)} W</td></tr>
              <tr><th>Core loss</th><td>P<sub>0</sub>·(V/V<sub>n</sub>)²</td><td>{f(P0, 0)} × ({f(V, 1)}/{f(Vbase, 1)})²</td><td className="o">{f(core, 0)} W</td></tr>
              <tr><th>Efficiency</th><td>η = P / (P + losses)</td><td>{f(P, 0)} / ({f(P, 0)} + {f((cu + core) / 1000, 2)}) kW</td><td className="o">{f(eff, 2)} %</td></tr>
            </tbody>
          </table>
        </section>
      </div>
    </div>
  );
}
