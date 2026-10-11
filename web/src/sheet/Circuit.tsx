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

/** A winding drawn as humps along the line from (x1,y1) to (x2,y2). */
function coil(x1: number, y1: number, x2: number, y2: number, color: string, n = 4, amp = 4.5) {
  const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy), ux = dx / len, uy = dy / len, nx = -uy, ny = ux;
  const pad = Math.min(10, len * 0.12), seg = (len - 2 * pad) / n;
  let d = `M${x1} ${y1} L${(x1 + ux * pad).toFixed(1)} ${(y1 + uy * pad).toFixed(1)}`;
  for (let i = 0; i < n; i++) {
    const sx = x1 + ux * (pad + seg * i), sy = y1 + uy * (pad + seg * i), ex = x1 + ux * (pad + seg * (i + 1)), ey = y1 + uy * (pad + seg * (i + 1));
    d += ` Q${((sx + ex) / 2 + nx * amp * 2).toFixed(1)} ${((sy + ey) / 2 + ny * amp * 2).toFixed(1)} ${ex.toFixed(1)} ${ey.toFixed(1)}`;
  }
  d += ` L${x2} ${y2}`;
  return <path key={`${x1}-${y1}-${x2}-${y2}`} d={d} fill="none" stroke={color} strokeWidth="2.4" />;
}

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
        <h2>Electrical circuit <span>live from the transformer</span></h2>
        <button className="unpin" onClick={onClose} aria-label="Close circuit page">×</button>
      </header>
      <div className="ck-body">
        <section className="ck-card ck-sld">
          <h3>Three-phase circuit <em>{(Vhv / 1000).toFixed(0)} kV / {(Vn / 1000).toFixed(3)} kV, Dyn11: delta on the HV side, star with a solidly earthed neutral on the LV side</em></h3>
          <svg viewBox="0 0 1180 372" className="ck-svg ck-sld-svg" role="img" aria-label="Three-phase transformer circuit">
            {/* ---- supply */}
            <circle cx="50" cy="160" r="30" fill="#fff" stroke={C.ink} strokeWidth="2" />
            <path d="M34 160 q8 -14 16 0 t16 0" fill="none" stroke={C.hv} strokeWidth="2.4" />
            <text x="50" y="212" textAnchor="middle" className="t b">Grid</text>
            <text x="50" y="226" textAnchor="middle" className="t m">{(Vhv / 1000).toFixed(0)} kV · {hz.toFixed(2)} Hz</text>
            {[110, 160, 210].map((y, k) => <path key={"fan" + k} d={`M80 160 L ${100} ${y}`} stroke={phc[k]} strokeWidth="2.2" fill="none" />)}
            {/* phase labels */}
            {[110, 160, 210].map((y, k) => <text key={"pl" + k} x="106" y={y - 6} className="t b" fill={phc[k]}>{"RYB"[k]}</text>)}
            {/* HV flow */}
            {[110, 160, 210].map((y, k) => <Flow key={"hf" + k} d={`M100 ${y} H 372`} color={phc[k]} n={6} />)}
            {/* surge arrester on R, one of three */}
            <path d="M150 110 V 70" stroke={C.ink} strokeWidth="1.6" fill="none" /><rect x="143" y="56" width="14" height="20" fill="#fff" stroke={C.ink} strokeWidth="1.6" /><path d="M150 56 V 44 M140 44 H160 M143 40 H157 M146 36 H154" stroke={C.ink} strokeWidth="1.5" fill="none" />
            <text x="168" y="62" className="t m">surge arresters ×3</text>
            {/* HV breaker, three poles */}
            {[110, 160, 210].map((y, k) => <g key={"hb" + k}><circle cx="222" cy={y} r="3" fill={C.ink} /><path d={`M222 ${y} L 244 ${y - 14}`} stroke={C.ink} strokeWidth="2.4" fill="none" /><circle cx="250" cy={y} r="3" fill={C.ink} /></g>)}
            <path d="M236 100 V 214" stroke={C.mute} strokeDasharray="3 3" strokeWidth="1.2" fill="none" />
            <text x="236" y="236" textAnchor="middle" className="t b">HV VCB 52-1</text><text x="236" y="250" textAnchor="middle" className="t ok">closed</text>
            {/* HV protection CTs */}
            {[110, 160, 210].map((y, k) => <circle key={"hc" + k} cx="300" cy={y} r="8" fill="#fff" stroke={C.ink} strokeWidth="1.8" />)}
            <text x="300" y="266" textAnchor="middle" className="t m">protection CTs</text>
            <text x="336" y="98" textAnchor="middle" className="t v">{f(Ihv, 1)} A</text>

            {/* ---- tank */}
            <rect x="372" y="34" width="418" height="300" rx="14" fill="#FBFAF6" stroke={C.ink} strokeWidth="2" strokeDasharray="7 4" />
            <text x="581" y="26" textAnchor="middle" className="t b">Transformer-1 · {Sn} kVA · ONAN · {f(K * 100, 0)} % loaded</text>
            {/* bushings */}
            {[110, 160, 210].map((y, k) => <g key={"hbu" + k}><circle cx="372" cy={y} r="7" fill="#fff" stroke={C.ink} strokeWidth="2" /><text x="385" y={y - 10} className="t m">1{"UVW"[k]}</text></g>)}
            {[110, 160, 210].map((y, k) => <g key={"lbu" + k}><circle cx="790" cy={y} r="7" fill="#fff" stroke={C.ink} strokeWidth="2" /><text x="768" y={y - 10} className="t m">2{"UVW"[k]}</text></g>)}
            <g><circle cx="790" cy="262" r="7" fill="#fff" stroke={C.ink} strokeWidth="2" /><text x="768" y="252" className="t m">2N</text></g>
            {/* HV delta: sides are the three coils; the tap changer sits on the U-W coil */}
            <path d="M380 110 H 530 M380 160 H 412 M380 210 H 530" stroke={C.hv} strokeWidth="2" fill="none" />
            {coil(412, 160, 530, 110, C.hv, 5)}{coil(530, 110, 530, 210, C.hv, 6)}{coil(530, 210, 412, 160, C.hv, 5)}
            <path d="M548 128 L 512 192" stroke={C.ink} strokeWidth="1.6" markerEnd="url(#ah)" fill="none" />
            <text x="470" y="258" textAnchor="middle" className="t m">tap changer on the HV coil, ±2 × 2.5 %</text>
            <text x="470" y="94" textAnchor="middle" className="t b" fill={C.hv}>HV delta</text>
            {/* core */}
            <path d="M582 88 V 232 M590 88 V 232" stroke={C.ink} strokeWidth="2.4" fill="none" />
            <path d="M582 88 H 590 M582 232 H 590" stroke={C.ink} strokeWidth="2.4" fill="none" />
            <text x="586" y="78" textAnchor="middle" className="t m">iron core</text>
            <text x="586" y="248" textAnchor="middle" className="t m">flux φ</text>
            {/* LV star */}
            {coil(640, 160, 730, 110, C.lv, 4)}{coil(640, 160, 730, 160, C.lv, 4)}{coil(640, 160, 730, 210, C.lv, 4)}{coil(640, 160, 640, 240, C.lv, 4)}
            <circle cx="640" cy="160" r="3.5" fill={C.ink} />
            <path d="M730 110 H 790 M730 160 H 790 M730 210 H 790" stroke={C.lv} strokeWidth="2" fill="none" />
            <path d="M640 240 V 262 H 790" stroke={C.lv} strokeWidth="2" fill="none" />
            <text x="690" y="94" textAnchor="middle" className="t b" fill={C.lv}>LV star</text>
            {/* instruments on the tank */}
            <g>
              <circle cx="420" cy="58" r="9" fill="#fff" stroke={C.ink} strokeWidth="1.4" /><text x="420" y="61" textAnchor="middle" className="t m" fontSize="8">OTI</text>
              <circle cx="452" cy="58" r="9" fill="#fff" stroke={C.ink} strokeWidth="1.4" /><text x="452" y="61" textAnchor="middle" className="t m" fontSize="8">WTI</text>
              <rect x="476" y="49" width="34" height="18" fill="#fff" stroke={C.ink} strokeWidth="1.4" /><text x="493" y="61" textAnchor="middle" className="t m" fontSize="8">Buchh.</text>
              <rect x="516" y="49" width="26" height="18" fill="#fff" stroke={C.ink} strokeWidth="1.4" /><text x="529" y="61" textAnchor="middle" className="t m" fontSize="8">PRD</text>
              <text x="556" y="62" className="t m" fontSize="9.5">oil {f(num(r.OTI_C), 0)} °C · winding {f(num(r.WTI_C), 0)} °C</text>
            </g>
            <path d="M420 67 V 300 M452 67 V 300 M493 67 V 300 M529 67 V 300" stroke={C.mute} strokeDasharray="2 3" strokeWidth="1" fill="none" />
            <rect x="404" y="294" width="150" height="30" rx="4" fill="#fff" stroke={C.ink} strokeWidth="1.6" /><text x="479" y="313" textAnchor="middle" className="t b">protection relay</text>
            <path d="M404 309 H 236 V 258" stroke="#B42318" strokeDasharray="5 3" strokeWidth="1.6" fill="none" markerEnd="url(#ah)" /><text x="320" y="324" textAnchor="middle" className="t m">trip</text>
            {/* tank earth */}
            <path d="M700 334 V 350 M690 350 H 710 M693 354 H 707 M696 358 H 704" stroke={C.ink} strokeWidth="1.6" fill="none" /><text x="718" y="354" className="t m">tank earth, CT-205 {f(num(r.IEARTH_A), 1)} A</text>

            {/* ---- LV side */}
            {[110, 160, 210].map((y, k) => <Flow key={"lf" + k} d={`M790 ${y} H 990`} color={phc[k]} n={5} />)}
            {[110, 160, 210].map((y, k) => <circle key={"lc" + k} cx="830" cy={y} r="8" fill="#fff" stroke={C.ink} strokeWidth="1.8" />)}
            <text x="830" y="236" textAnchor="middle" className="t m">CT-201..203</text>
            <text x="880" y="98" textAnchor="middle" className="t v">{f(I, 0)} A</text>
            {[110, 160, 210].map((y, k) => <g key={"lb" + k}><circle cx="900" cy={y} r="3" fill={C.ink} /><path d={`M900 ${y} L 922 ${y - 14}`} stroke={C.ink} strokeWidth="2.4" fill="none" /><circle cx="928" cy={y} r="3" fill={C.ink} /></g>)}
            <path d="M914 100 V 214" stroke={C.mute} strokeDasharray="3 3" strokeWidth="1.2" fill="none" />
            <text x="914" y="236" textAnchor="middle" className="t b">LV ACB 52-2</text><text x="914" y="250" textAnchor="middle" className="t ok">closed</text>
            {/* neutral: CT and earth */}
            <path d="M797 262 H 860" stroke={C.lv} strokeWidth="2" fill="none" /><circle cx="826" cy="262" r="8" fill="#fff" stroke={C.ink} strokeWidth="1.8" /><path d="M860 262 V 284 M850 284 H 870 M853 288 H 867 M856 292 H 864" stroke={C.ink} strokeWidth="1.6" fill="none" />
            <text x="810" y="288" textAnchor="middle" className="t m" fontSize="9.5">CT-204 · {f(num(r.IN), 1)} A</text>
            <text x="880" y="300" className="t m">neutral solidly earthed</text>
            {/* busbar, load, meter */}
            <path d="M990 96 V 224" stroke={C.ink} strokeWidth="5" fill="none" />
            <path d="M990 160 H 1020" stroke={C.lv} strokeWidth="2" fill="none" />
            <rect x="1020" y="104" width="148" height="112" rx="6" fill="#fff" stroke={C.ink} strokeWidth="2" />
            <text x="1094" y="130" textAnchor="middle" className="t b">Campus load</text>
            <text x="1094" y="152" textAnchor="middle" className="t v">{f(P, 0)} kW</text>
            <text x="1094" y="170" textAnchor="middle" className="t m">{f(Q, 0)} kvar · PF {f(pf, 2)}</text>
            <text x="1094" y="190" textAnchor="middle" className="t m">{f(V, 0)} V per phase</text>
            <text x="1094" y="204" textAnchor="middle" className="t m">{f(V * Math.sqrt(3), 0)} V line</text>
            <rect x="1000" y="262" width="130" height="40" rx="4" fill="#fff" stroke={C.ink} strokeWidth="1.6" /><text x="1065" y="280" textAnchor="middle" className="t b">PM-201 meter</text><text x="1065" y="294" textAnchor="middle" className="t m">S P Q PF Hz</text>
            <path d="M990 224 V 244 H 1065 V 262" stroke={C.mute} strokeDasharray="3 3" strokeWidth="1.2" fill="none" />
            <defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10z" fill={C.ink} /></marker></defs>
            <text x="590" y="368" textAnchor="middle" className="t m">Losses now: core {f(core, 0)} W + copper {f(cu, 0)} W = {f(core + cu, 0)} W · efficiency {f(eff, 2)} %</text>
          </svg>
          <table className="ck-rat">
            <tbody>
              <tr><th>Rating</th><td>{Sn} kVA, ONAN</td><th>HV rated</th><td>{(Vhv / 1000).toFixed(0)} kV, {f((Sn * 1000) / (Math.sqrt(3) * Vhv), 1)} A</td><th>LV rated</th><td>{Vn} V, {f(Ir, 0)} A</td></tr>
              <tr><th>Vector group</th><td>Dyn11 (LV leads HV by 30°)</td><th>Impedance</th><td>{(UK * 100).toFixed(0)} % (assumed)</td><th>Losses (rated)</th><td>core {f(P0, 0)} W · load {f(Pk, 0)} W</td></tr>
              <tr><th>Loading now</th><td>{f(K * 100, 0)} % · {f(I, 0)} A of {f(Ir, 0)} A</td><th>HV current now</th><td>{f(Ihv, 1)} A line</td><th>Voltage drop / efficiency</th><td>{f(reg, 2)} % · {f(eff, 2)} %</td></tr>
            </tbody>
          </table>
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
