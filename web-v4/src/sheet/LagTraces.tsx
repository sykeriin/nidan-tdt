// Thermal lag over the 18 h before the cursor. Load K (ink, steps at once); hot-spot and top-oil (blue, solid)
// chasing their steady-state targets (blue, dashed): the winding follows within minutes (τw), the oil over
// hours (τo). τo is dimensioned on the time axis. Values from frames: load_pu, twin_hs_C, hot_spot_ss_C,
// twin_oil_C, top_oil_ss_C, tau_oil_min, tau_winding_min.
import { player, usePlayerIndex } from "../player/player";

const num = (v: unknown) => (typeof v === "number" ? v : null);
const WIN_H = 18;
const Wd = 212, Hd = 104, L = 4, R = 26, T = 18, B = 16;

export function LagTraces() {
  const i = usePlayerIndex();
  const f = player.frames;
  if (!f || i < 0) return null;
  const t1 = f.t[i], t0 = t1 - WIN_H * 3_600_000;
  let j = i;
  while (j > 0 && f.t[j - 1] >= t0) j--;
  const idx = Array.from({ length: i - j + 1 }, (_, k) => j + k);
  const col = (k: string) => idx.map((n) => num(f.cols[k]?.[n]));
  const K = col("load_pu"), hs = col("twin_hs_C"), hss = col("hot_spot_ss_C"), oil = col("twin_oil_C"), oss = col("top_oil_ss_C");
  const temps = [...hs, ...hss, ...oil, ...oss].filter((v): v is number => v !== null);
  if (!temps.length) return null;
  const lo = Math.floor(Math.min(...temps) / 5) * 5, hi = Math.ceil(Math.max(...temps) / 5) * 5 || lo + 5;
  const kmax = Math.max(0.5, ...K.filter((v): v is number => v !== null)) * 1.1;
  const x = (n: number) => L + ((f.t[n] - t0) / (t1 - t0)) * (Wd - L - R);
  const yT = (c: number) => T + (1 - (c - lo) / (hi - lo || 1)) * (Hd - T - B);
  const yK = (k: number) => T + (1 - k / kmax) * (Hd - T - B);
  const path = (vals: (number | null)[], yf: (v: number) => number, step = false) => {
    let d = "", prev: number | null = null;
    vals.forEach((v, k) => {
      if (v === null) { prev = null; return; }
      const X = x(idx[k]).toFixed(1), Y = yf(v).toFixed(1);
      d += prev === null ? `M${X} ${Y}` : step ? `H${X}V${Y}` : `L${X} ${Y}`;
      prev = v;
    });
    return d;
  };
  const tauO = num(player.value("tau_oil_min", i)), tauW = num(player.value("tau_winding_min", i));
  const tauPx = tauO === null ? 0 : (tauO * 60_000 / (t1 - t0)) * (Wd - L - R);
  const xe = Wd - R;
  return (
    <figure className="lag" aria-label="Thermal lag, last 18 hours">
      <figcaption>Thermal lag <span>last {WIN_H} h</span></figcaption>
      <svg width={Wd} height={Hd} aria-hidden="true">
        <path d={path(K, yK, true)} className="k" />
        <path d={path(hss, yT)} className="ss" />
        <path d={path(hs, yT)} className="tw" />
        <path d={path(oss, yT)} className="ss" />
        <path d={path(oil, yT)} className="tw" />
        <line x1={xe} x2={xe} y1={T - 4} y2={Hd - B} className="now" />
        {tauO !== null && <g className="tau">
          <line x1={xe - tauPx} x2={xe} y1={7} y2={7} />
          <line x1={xe - tauPx} x2={xe - tauPx} y1={3} y2={11} /><line x1={xe} x2={xe} y1={3} y2={11} />
          <text x={xe - tauPx - 3} y={10} textAnchor="end">τo {tauO.toFixed(0)} min{tauW !== null ? `, τw ${tauW.toFixed(0)} min` : ""}</text>
        </g>}
        <text x={xe + 3} y={yT(hs[hs.length - 1] ?? lo) + 3} className="end">hot-spot</text>
        <text x={xe + 3} y={yT(oil[oil.length - 1] ?? lo) + 3} className="end">oil</text>
        <text x={L} y={Hd - 3} className="axl">−{WIN_H} h</text>
        <text x={xe} y={Hd - 3} className="axl" textAnchor="end">now</text>
      </svg>
      <p className="lag-key"><i className="k" />load K <i className="tw" />twin <i className="ss" />steady</p>
    </figure>
  );
}
