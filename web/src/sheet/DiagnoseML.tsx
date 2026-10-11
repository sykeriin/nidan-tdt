// DIAGNOSE: three detectors, one verdict. The physics twin is the primary detector (its findings are numbered on the
// parts); an Isolation Forest and a Prophet forecast are shown beside it as independent second opinions.
import { useQuery, keepPreviousData } from "@tanstack/react-query";

interface IF {
  available: boolean; reason?: string; t: string[]; score: number[]; threshold: number; trained_on: string;
  episodes: { start: string; end: string; peak: number; driver: string; driver_z: number }[];
  now: { score: number; flagged: boolean; driver: string }; episode_count: number; note: string;
}
interface PR {
  available: boolean; reason?: string; target: string; t: string[]; yhat: (number | null)[]; lo: (number | null)[]; hi: (number | null)[];
  actual: (number | null)[]; breach: boolean[]; cut: string; now: string; mae_24h_C: number | null; outside_band_hours: number;
  hours_checked: number; first_breach: string | null; trained_hours: number; verdict: string; note: string;
}
export interface MlView { t: string; isolation_forest: IF; prophet: PR }

const hourOf = (t: string) => t.slice(0, 13);
export const useMl = (dataset: string, t: string | null, enabled: boolean) =>
  useQuery({
    queryKey: ["ml", dataset, t && hourOf(t)], enabled: enabled && !!t, staleTime: Infinity, retry: false, placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await fetch(`/api/datasets/${encodeURIComponent(dataset)}/ml?t=${encodeURIComponent(t!)}`);
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `${res.status} ${res.statusText}`);
      return (await res.json()) as MlView;
    },
  });

const ms = (s: string) => Date.parse(s);
const dayLabel = (t: number) => new Date(t).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });

function ForestChart({ f }: { f: IF }) {
  const W = 520, H = 120, L = 30, R = 8, T = 8, B = 18;
  const t = f.t.map(ms);
  const t0 = t[0], t1 = t[t.length - 1];
  const top = Math.max(1.6, ...f.score);
  const x = (v: number) => L + ((v - t0) / (t1 - t0 || 1)) * (W - L - R);
  const y = (v: number) => T + (1 - v / top) * (H - T - B);
  const line = f.score.map((v, k) => `${k ? "L" : "M"}${x(t[k]).toFixed(1)} ${y(v).toFixed(1)}`).join("");
  const ticks = [0, 1, 2].filter((v) => v <= top);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="ml-chart" role="img" aria-label="Isolation Forest anomaly score">
      {f.episodes.map((e, n) => { const a = Math.max(x(ms(e.start)), L), b = Math.min(x(ms(e.end)), W - R); return b > L && a < W - R ? <rect key={n} x={a} y={T} width={Math.max(3, b - a)} height={H - T - B} className="ep" /> : null; })}
      {ticks.map((v) => <g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className="g" /><text x={L - 4} y={y(v) + 3} textAnchor="end">{v}</text></g>)}
      <line x1={L} x2={W - R} y1={y(f.threshold)} y2={y(f.threshold)} className="thr" />
      <text x={W - R} y={y(f.threshold) - 3} textAnchor="end" className="thr-l">unusual above 1</text>
      <path d={line} className="score" />
      <circle cx={x(t1)} cy={y(f.score[f.score.length - 1])} r={3.4} className={f.now.flagged ? "dot bad" : "dot"} />
      {[0, 0.5, 1].map((k) => { const tv = t0 + (t1 - t0) * k; return <text key={k} x={x(tv)} y={H - 4} textAnchor={k === 0 ? "start" : k === 1 ? "end" : "middle"}>{dayLabel(tv)}</text>; })}
    </svg>
  );
}

function ProphetChart({ p }: { p: PR }) {
  const W = 520, H = 130, L = 30, R = 8, T = 8, B = 18;
  const t = p.t.map(ms);
  const t0 = t[0], t1 = t[t.length - 1], tNow = ms(p.now), tCut = ms(p.cut);
  const vals = [...p.lo, ...p.hi, ...p.actual].filter((v): v is number => v != null);
  const lo = Math.floor(Math.min(...vals) / 5) * 5, hi = Math.ceil(Math.max(...vals) / 5) * 5;
  const x = (v: number) => L + ((v - t0) / (t1 - t0 || 1)) * (W - L - R);
  const y = (v: number) => T + (1 - (v - lo) / (hi - lo || 1)) * (H - T - B);
  const path = (a: (number | null)[], from = 0) => a.map((v, k) => (v == null || k < from ? "" : `${k && a[k - 1] != null && k > from ? "L" : "M"}${x(t[k]).toFixed(1)} ${y(v).toFixed(1)}`)).join("");
  const band = p.lo.map((v, k) => `${k ? "L" : "M"}${x(t[k]).toFixed(1)} ${y(v ?? lo).toFixed(1)}`).join("") +
    p.hi.map((_, k) => { const j = p.hi.length - 1 - k; return `L${x(t[j]).toFixed(1)} ${y(p.hi[j] ?? hi).toFixed(1)}`; }).join("") + "Z";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="ml-chart" role="img" aria-label="Prophet expected versus actual top-oil temperature">
      <rect x={x(tNow)} y={T} width={Math.max(0, W - R - x(tNow))} height={H - T - B} className="future" />
      <rect x={x(tCut)} y={T} width={Math.max(0, x(tNow) - x(tCut))} height={H - T - B} className="test" />
      {[lo, (lo + hi) / 2, hi].map((v) => <g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className="g" /><text x={L - 4} y={y(v) + 3} textAnchor="end">{v.toFixed(0)}</text></g>)}
      <path d={band} className="band" />
      <path d={path(p.yhat)} className="yhat" />
      <path d={path(p.actual)} className="actual" />
      {p.t.map((_, k) => p.breach[k] && p.actual[k] != null ? <circle key={k} cx={x(t[k])} cy={y(p.actual[k]!)} r={3} className="dot bad" /> : null)}
      <text x={x(tCut) + 3} y={T + 9} className="lbl">last 24 h: tested</text>
      <text x={x(tNow) + 3} y={T + 9} className="lbl">next 24 h</text>
      {[0, 0.5, 1].map((k) => { const tv = t0 + (t1 - t0) * k; return <text key={k} x={x(tv)} y={H - 4} textAnchor={k === 0 ? "start" : k === 1 ? "end" : "middle"}>{dayLabel(tv)}</text>; })}
    </svg>
  );
}

export function DiagnoseML({ dataset, iso, physicsCount, physicsWorst }: { dataset: string; iso: string | null; physicsCount: number; physicsWorst: string | null }) {
  const q = useMl(dataset, iso, true);
  const d = q.data;
  const f = d?.isolation_forest, p = d?.prophet;
  const fVote = f?.available ? (f.now.flagged ? "flag" : "ok") : "na";
  const pVote = p?.available ? (p.outside_band_hours > 0 ? "flag" : "ok") : "na";
  const phVote = physicsCount > 0 ? "flag" : "ok";
  const flags = [fVote, pVote, phVote].filter((v) => v === "flag").length;
  const verdict = flags === 0 ? "All three agree: normal." : flags === 1 ? "One detector is raising a flag: worth a look, not yet a finding." : flags === 2 ? "Two detectors agree something is off." : "All three detectors agree: act on the findings.";
  return (
    <section className="st-trends ml-strip" aria-label="Machine-learning second opinions">
      <div className="st-card ml-card">
        <h3>Isolation Forest <em>is the day unlike the first week?</em></h3>
        {q.isLoading && <p className="ml-wait">Training the forest…</p>}
        {q.error && <p className="ml-wait">{(q.error as Error).message}</p>}
        {f && !f.available && <p className="ml-wait">{f.reason}</p>}
        {f?.available && <>
          <ForestChart f={f} />
          <p className="ml-line"><b className={f.now.flagged ? "bad" : "ok"}>{f.now.flagged ? "Unusual now" : "Typical now"}</b> score {f.now.score.toFixed(2)} · main driver {f.now.driver} · {f.episode_count} unusual stretch{f.episode_count === 1 ? "" : "es"} so far</p>
          <p className="ml-note">{f.trained_on}. Inputs: twin residual, load, phase unbalance, oil-level trend.</p>
        </>}
      </div>
      <div className="st-card ml-card">
        <h3>Prophet <em>what should the oil temperature have been?</em></h3>
        {q.isLoading && <p className="ml-wait">Fitting the forecast… (a few seconds the first time)</p>}
        {p && !p.available && <p className="ml-wait">{p.reason}</p>}
        {p?.available && <>
          <ProphetChart p={p} />
          <p className="ml-line"><b className={p.outside_band_hours > 0 ? "bad" : "ok"}>{p.outside_band_hours > 0 ? `${p.outside_band_hours} h outside the band` : "Inside the band"}</b> · average miss {p.mae_24h_C ?? "—"} °C over {p.hours_checked} h</p>
          <p className="ml-note"><i className="k-act" /> actual <i className="k-fc" /> Prophet <i className="k-bd" /> 95 % band · {p.target}</p>
        </>}
      </div>
      <div className="st-card ml-card ml-vote">
        <h3>Do the detectors agree?</h3>
        <ul>
          <li><span>Physics twin</span><b className={phVote}>{physicsCount > 0 ? `${physicsCount} finding${physicsCount === 1 ? "" : "s"}${physicsWorst ? ` (${physicsWorst})` : ""}` : "no findings"}</b></li>
          <li><span>Isolation Forest</span><b className={fVote}>{fVote === "na" ? "n/a" : fVote === "flag" ? "unusual" : "typical"}</b></li>
          <li><span>Prophet</span><b className={pVote}>{pVote === "na" ? "n/a" : pVote === "flag" ? "off forecast" : "on forecast"}</b></li>
        </ul>
        <p className="ml-verdict">{verdict}</p>
        <p className="ml-note">The physics twin is the primary detector. The forest and Prophet are advisory: they can flag an unusual day without a fault, and miss a slow one.</p>
      </div>
    </section>
  );
}
