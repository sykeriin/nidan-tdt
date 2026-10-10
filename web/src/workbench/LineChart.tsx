// A small SVG line chart in the sheet's ink-and-blue style. No chart library: the workbench needs lines, a baseline and a marker.
interface S { name: string; x: number[]; y: number[]; cls: "ink" | "twin" | "faint"; dash?: boolean }

const nice = (lo: number, hi: number, n = 5) => {
  const span = hi - lo || 1, raw = span / n, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? mag * 10;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
};

export function LineChart({ series, vlines = [], xLabel, yLabel, yMax }: {
  series: S[]; vlines?: { x: number; label: string }[]; xLabel: string; yLabel: string; yMax?: number
}) {
  const W = 760, H = 250, m = { l: 48, r: 14, t: 12, b: 36 };
  const xs = series.flatMap((s) => s.x), ys = series.flatMap((s) => s.y).filter((v) => Number.isFinite(v));
  if (!xs.length || !ys.length) return null;
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const y0 = Math.min(...ys, yMax != null ? 0 : Infinity), y1 = yMax ?? Math.max(...ys);
  const pad = yMax != null ? 0 : (y1 - y0) * 0.06 || 1;
  const lo = y0 - pad, hi = y1 + pad;
  const X = (v: number) => m.l + ((v - x0) / (x1 - x0 || 1)) * (W - m.l - m.r);
  const Y = (v: number) => m.t + (1 - (v - lo) / (hi - lo || 1)) * (H - m.t - m.b);
  const path = (s: S) => s.x.map((x, i) => `${i ? "L" : "M"}${X(x).toFixed(1)} ${Y(s.y[i]).toFixed(1)}`).join(" ");
  return (
    <svg className="wb-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${yLabel} against ${xLabel}`}>
      {nice(lo, hi).map((v) => (<g key={`y${v}`}><line x1={m.l} x2={W - m.r} y1={Y(v)} y2={Y(v)} className="g" /><text x={m.l - 6} y={Y(v) + 3} textAnchor="end">{v}</text></g>))}
      {nice(x0, x1, 6).map((v) => (<g key={`x${v}`}><line x1={X(v)} x2={X(v)} y1={m.t} y2={H - m.b} className="g" /><text x={X(v)} y={H - m.b + 14} textAnchor="middle">{v}</text></g>))}
      <line x1={m.l} x2={W - m.r} y1={H - m.b} y2={H - m.b} className="axis" />
      <text x={(m.l + W - m.r) / 2} y={H - 4} textAnchor="middle" className="lab">{xLabel}</text>
      <text x={12} y={(m.t + H - m.b) / 2} textAnchor="middle" className="lab" transform={`rotate(-90 12 ${(m.t + H - m.b) / 2})`}>{yLabel}</text>
      {vlines.map((v) => (<g key={v.label}><line x1={X(v.x)} x2={X(v.x)} y1={m.t} y2={H - m.b} className="vl" /><text x={X(v.x) + 4} y={m.t + 10} className="vlt">{v.label}</text></g>))}
      {series.map((s) => <path key={s.name} d={path(s)} className={`ln ${s.cls}${s.dash ? " dash" : ""}`} />)}
      {series.filter((s) => s.cls !== "faint").map((s, i) => (
        <text key={s.name} x={W - m.r - 4} y={m.t + 12 + i * 13} textAnchor="end" className={`key ${s.cls}`}>{s.name}</text>
      ))}
    </svg>
  );
}
