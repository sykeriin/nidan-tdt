// Section thermometer, drawn as the IEC 60076-7 thermal diagram: relative height in the winding (bottom → top)
// against temperature. Oil line from bottom oil to top oil; winding line parallel to it through the average
// winding temperature; hot-spot at the top, H·gr·K^y beyond the top oil; ambient dashed. Values from frames.
import { player, usePlayerIndex } from "../player/player";
import { trustOf } from "../data/fields";

const num = (v: unknown) => (typeof v === "number" ? v : null);
const Wd = 236, Hd = 150, L = 40, R = 12, T = 24, B = 22;

export function ThermalDiagram({ meterOnly, otiSuspect }: { meterOnly: boolean; otiSuspect: boolean }) {
  const i = usePlayerIndex();
  if (i < 0) return null;
  const v = (k: string) => num(player.value(k, i));
  const amb = v("amb_C"), bot = v("bottom_oil_C"), top = v("twin_oil_C"), avgW = v("avg_winding_C");
  const hs = v("twin_hs_C"), grad = v("hs_gradient_K");
  const otiRaw = meterOnly ? null : v("OTI_C");
  const oti = otiRaw !== null && trustOf("OTI_C", otiRaw, String(player.value("dq_flags", i) ?? ""), otiSuspect) !== "suspect" ? otiRaw : null;
  const hsM = player.value("ageing_source", i) === "measured" && !meterOnly ? v("hs_ageing_C") : null;
  if (amb === null || bot === null || top === null || hs === null) {
    return <figure className="thermdiag"><figcaption>Section thermometer</figcaption><p className="field-note">No load or ambient at this sample: the twin has no thermal state.</p></figure>;
  }
  const vals = [amb, bot, top, hs, oti, hsM].filter((x): x is number => x !== null);
  const lo = Math.floor((Math.min(...vals) - 3) / 10) * 10, hi = Math.ceil((Math.max(...vals) + 3) / 10) * 10;
  const x = (c: number) => L + ((c - lo) / (hi - lo)) * (Wd - L - R);
  const y = (h: number) => T + (1 - h) * (Hd - T - B);
  const half = (top - bot) / 2; // drawing: the winding line runs parallel to the oil line
  const ticks: number[] = [];
  for (let c = lo; c <= hi; c += hi - lo > 60 ? 20 : 10) ticks.push(c);
  return (
    <figure className="thermdiag" aria-label="Section thermometer: temperature against height">
      <figcaption>Section thermometer <span>IEC 60076-7 thermal diagram</span></figcaption>
      <svg width={Wd} height={Hd} aria-hidden="true">
        {/* axes */}
        <line x1={L} x2={Wd - R} y1={y(0)} y2={y(0)} className="ax" />
        <line x1={L} x2={L} y1={y(0)} y2={y(1) - 6} className="ax" />
        <text x={L - 4} y={y(1) + 3} className="axl" textAnchor="end">top</text>
        <text x={L - 4} y={y(0) + 3} className="axl" textAnchor="end">bottom</text>
        {ticks.map((c) => (
          <g key={c} transform={`translate(${x(c)},${y(0)})`}><line y2={4} className="ax" /><text y={14} textAnchor="middle" className="axl">{c}</text></g>
        ))}
        <text x={Wd - R} y={Hd - 2} className="axl" textAnchor="end">°C</text>
        {/* ambient */}
        <line x1={x(amb)} x2={x(amb)} y1={y(0)} y2={y(1) - 4} className="amb" />
        <text x={x(amb) - 3} y={y(0.5)} className="lbl axl" textAnchor="end" transform={`rotate(-90 ${x(amb) - 3} ${y(0.5)})`}>ambient</text>
        {/* oil and winding lines */}
        <line x1={x(bot)} y1={y(0)} x2={x(top)} y2={y(1)} className="oil" />
        {avgW !== null && <line x1={x(avgW - half)} y1={y(0)} x2={x(avgW + half)} y2={y(1)} className="wind" />}
        <circle cx={x(bot)} cy={y(0)} r={2.5} className="pt t" />
        <circle cx={x(top)} cy={y(1)} r={2.5} className="pt t" />
        {/* hot-spot and its gradient over top oil, dimensioned */}
        <line x1={x(top)} x2={x(hs)} y1={y(1) - 10} y2={y(1) - 10} className="dim" markerStart="url(#tick)" markerEnd="url(#tick)" />
        <line x1={x(top)} x2={x(top)} y1={y(1)} y2={y(1) - 13} className="ext" />
        <line x1={x(hs)} x2={x(hs)} y1={y(1)} y2={y(1) - 13} className="ext" />
        <text x={(x(top) + x(hs)) / 2} y={y(1) - 13} textAnchor="middle" className="diml">H·gr·K^y {grad === null ? "—" : grad.toFixed(1)} K</text>
        <rect x={x(hs) - 3} y={y(1) - 3} width={6} height={6} className="pt t" />
        {oti !== null && <circle cx={x(oti)} cy={y(1)} r={3} className="pt m" />}
        {hsM !== null && <rect x={x(hsM) - 3.5} y={y(1) - 3.5} width={7} height={7} className="pt m hollow" />}
        <defs>
          <marker id="tick" viewBox="-3 -3 6 6" markerWidth={6} markerHeight={6} orient="auto"><path d="M-2 2 L2 -2" className="dimtick" /></marker>
        </defs>
      </svg>
      <ul className="td-key">
        <li className="t">● top oil {top.toFixed(1)}</li>{oti !== null ? <li className="m">● measured {oti.toFixed(1)}</li> : <li />}
        <li className="t">■ hot-spot {hs.toFixed(1)}</li>{hsM !== null ? <li className="m">□ measured {hsM.toFixed(1)}</li> : <li />}
        <li className="t">● bottom oil {bot.toFixed(1)} <span className="est">est.</span></li><li className="a">┆ ambient {amb.toFixed(1)}</li>
        <li className="t" style={{ gridColumn: "1 / 3" }}>– · – winding, avg {avgW === null ? "—" : avgW.toFixed(1)} <span className="est">est.</span></li>
      </ul>
    </figure>
  );
}
