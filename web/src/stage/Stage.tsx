// The stage: cards around the 3D model. Left: temperature thermometers and the load dial. Right: health ring and the AC
// power flow. Below: three-day trends. Everything reads the replay clock (player), so it moves with the model.
import { useMemo } from "react";
import { player, usePlayerIndex } from "../player/player";

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const fmt = (v: number | null, d = 0) => (v == null ? "—" : v.toFixed(d));
const HOUR = 3600_000;

// ---------------------------------------------------------------- data windows
interface Win { t: number[]; v: Record<string, (number | null)[]>; now: number; nowAt: number }
// `ahead` hours after the cursor are included so a chart is never empty at the start of a replay; they are drawn faint.
function useWindow(keys: string[], hours: number, ahead = 0): Win | null {
  const i = usePlayerIndex();
  const rev = player.rev;
  return useMemo(() => {
    const f = player.frames;
    if (!f || i < 0) return null;
    const t1 = f.t[i], t0 = t1 - hours * HOUR, tEnd = t1 + ahead * HOUR;
    let lo = i, hi = i;
    while (lo > 0 && f.t[lo - 1] >= t0) lo--;
    while (hi < f.t.length - 1 && f.t[hi + 1] <= tEnd) hi++;
    const step = Math.max(1, Math.floor((hi - lo) / 240));
    const t: number[] = [];
    let nowAt = -1;
    const v: Record<string, (number | null)[]> = Object.fromEntries(keys.map((k) => [k, []]));
    for (let k = lo; k <= hi; k += step) {
      if (nowAt < 0 && f.t[k] >= t1) nowAt = t.length;
      t.push(f.t[k]);
      for (const key of keys) v[key].push(num(f.cols[key]?.[k]));
    }
    return { t, v, now: t1, nowAt: nowAt < 0 ? t.length - 1 : nowAt };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [i, rev, hours, ahead, keys.join(",")]);
}
const last = (a: (number | null)[]) => (a.length ? a[a.length - 1] : null);

// ---------------------------------------------------------------- small drawing helpers
function heat(v: number): string {
  const k = Math.max(0, Math.min(1, (v - 20) / 110)); // 20 °C cold, 130 °C hot
  const stops = [[36, 56, 140], [130, 52, 150], [214, 86, 70], [245, 160, 40], [252, 232, 140]];
  const x = k * (stops.length - 1), a = Math.floor(x), b = Math.min(stops.length - 1, a + 1), f = x - a;
  const c = stops[a].map((s, n) => Math.round(s + (stops[b][n] - s) * f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}
function Path({ xs, ys, x0, x1, y0, y1, w, h, cls }: { xs: number[]; ys: (number | null)[]; x0: number; x1: number; y0: number; y1: number; w: number; h: number; cls: string }) {
  let d = "";
  let pen = false;
  ys.forEach((y, k) => {
    if (y == null) { pen = false; return; }
    d += `${pen ? "L" : "M"}${(((xs[k] - x0) / (x1 - x0 || 1)) * w).toFixed(1)} ${(h - ((y - y0) / (y1 - y0 || 1)) * h).toFixed(1)} `;
    pen = true;
  });
  return <path d={d} className={cls} />;
}

function Card({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  return <section className={`st-card ${className}`}><h3>{title}</h3>{children}</section>;
}

// ---------------------------------------------------------------- view modes (on the model)
export type ViewMode = "normal" | "xray" | "cut";
export function ViewModes({ view, onView }: { view: ViewMode; onView: (v: ViewMode) => void }) {
  const items: [ViewMode, string, string][] = [["normal", "Normal", "Closed tank, as it looks outside"], ["xray", "X-ray", "See-through tank: oil, windings and core"], ["cut", "Cut open", "Section A-A: the tank cut in half"]];
  return (
    <div className="st-modes" role="group" aria-label="3D view">
      {items.map(([id, label, hint]) => (
        <button key={id} className={view === id ? "on" : ""} aria-pressed={view === id} title={hint} onClick={() => onView(id)}>{label}</button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- left column
function Thermometers() {
  const i = usePlayerIndex();
  const r = i >= 0 ? player.row(i) : {};
  const rows: { name: string; v: number | null; meas: number | null; marks?: number[] }[] = [
    { name: "Bottom oil", v: num(r.bottom_oil_C), meas: null },
    { name: "Top oil", v: num(r.twin_oil_C), meas: num(r.OTI_C), marks: [85, 95] },
    { name: "Hot spot", v: num(r.twin_hs_C), meas: num(r.WTI_C), marks: [98, 120] },
  ];
  const H = 120, max = 140;
  const y = (v: number) => H - (Math.max(0, Math.min(max, v)) / max) * H;
  return (
    <Card title="Temperatures">
      <div className="st-thermo">
        {rows.map((t) => (
          <div key={t.name} className="st-th">
            <svg viewBox={`0 0 56 ${H + 4}`} role="img" aria-label={`${t.name} ${fmt(t.v)} degrees`}>
              <rect x="20" y="2" width="16" height={H} rx="8" className="tube" />
              {t.v != null && <rect x="20" y={y(t.v) + 2} width="16" height={H - y(t.v)} rx="8" style={{ fill: heat(t.v) }} />}
              {(t.marks ?? []).map((m) => <line key={m} x1="14" x2="42" y1={y(m) + 2} y2={y(m) + 2} className="mark" />)}
              {t.meas != null && <path d={`M46 ${y(t.meas) + 2} l8 -4 v8 z`} className="meas" />}
            </svg>
            <b>{fmt(t.v)}<small>°C</small></b>
            <span>{t.name}</span>
          </div>
        ))}
      </div>
      <p className="st-note">Twin values. The orange marker is the sensor, the lines are the alarm and limit levels.</p>
    </Card>
  );
}

function LoadDial() {
  const w = useWindow(["load_pu"], 72);
  const pct = w ? (last(w.v.load_pu) ?? 0) * 100 : null;
  const R = 52, cx = 70, cy = 66, max = 140;
  const ang = (p: number) => Math.PI * (1 - Math.min(max, Math.max(0, p)) / max);
  const pt = (p: number, rad: number) => [cx + rad * Math.cos(ang(p)), cy - rad * Math.sin(ang(p))];
  const arc = (a: number, b: number) => { const [x1, y1] = pt(a, R), [x2, y2] = pt(b, R); return `M${x1.toFixed(1)} ${y1.toFixed(1)} A${R} ${R} 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)}`; };
  const colour = pct == null ? "#999" : pct >= 100 ? "var(--bad)" : pct >= 90 ? "var(--warn)" : "var(--twin)";
  return (
    <Card title="Load">
      <svg viewBox="0 0 140 84" className="st-dial" role="img" aria-label={`Load ${fmt(pct)} percent of rating`}>
        <path d={arc(0, max)} className="track" />
        {pct != null && pct > 0.5 && <path d={arc(0, pct)} className="val" style={{ stroke: colour }} />}
        {[90, 100].map((m) => { const [x1, y1] = pt(m, R - 9), [x2, y2] = pt(m, R + 9); return <line key={m} x1={x1} y1={y1} x2={x2} y2={y2} className="mk" />; })}
        <text x={cx} y={cy - 4} textAnchor="middle" className="big">{fmt(pct)}</text>
        <text x={cx} y={cy + 12} textAnchor="middle" className="sm">% of rating</text>
      </svg>
      {w && (
        <svg viewBox="0 0 200 34" preserveAspectRatio="none" className="st-spark" aria-hidden>
          <Path xs={w.t} ys={w.v.load_pu.map((v) => (v == null ? null : v * 100))} x0={w.t[0]} x1={w.now} y0={0} y1={Math.max(100, ...w.v.load_pu.map((v) => (v ?? 0) * 100))} w={200} h={32} cls="ln ink" />
        </svg>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- right column
function HealthRing() {
  const i = usePlayerIndex();
  const r = i >= 0 ? player.row(i) : {};
  const score = num(r.health_score);
  const band = String(r.health_band ?? "").toLowerCase();
  const C = 2 * Math.PI * 46, v = Math.max(0, Math.min(100, score ?? 0));
  const col = band === "green" ? "var(--ok)" : band === "yellow" ? "var(--warn)" : band === "red" ? "var(--bad)" : "#999";
  const subs = ["thermal", "ageing", "loading", "electrical", "integrity"].map((k) => [k, num(r[`health_${k}`])] as const);
  return (
    <Card title="Health index">
      <div className="st-health">
        <svg viewBox="0 0 110 110" role="img" aria-label={`Health index ${fmt(score)} of 100`}>
          <circle cx="55" cy="55" r="46" className="track" />
          <circle cx="55" cy="55" r="46" className="arc" style={{ stroke: col, strokeDasharray: `${(v / 100) * C} ${C}` }} transform="rotate(-90 55 55)" />
          <text x="55" y="60" textAnchor="middle" className="big">{fmt(score)}</text>
        </svg>
        <ul>
          {subs.map(([k, s]) => (
            <li key={k}><span>{k}</span><i><u style={{ width: `${s ?? 0}%`, background: s != null && s < 60 ? "var(--bad)" : s != null && s < 80 ? "var(--warn)" : "var(--ink)" }} /></i></li>
          ))}
        </ul>
      </div>
    </Card>
  );
}

function FlowMini() {
  const w = useWindow(["IR", "IY", "IB", "VR", "VY", "VB", "PF", "losses_total_W"], 24);
  const f = (k: string) => (w ? last(w.v[k]) : null);
  const I = ["IR", "IY", "IB"].map(f), V = ["VR", "VY", "VB"].map(f), pf = f("PF"), loss = f("losses_total_W");
  const iAvg = I.every((x) => x != null) ? (I as number[]).reduce((a, b) => a + b, 0) / 3 : null;
  const vAvg = V.every((x) => x != null) ? (V as number[]).reduce((a, b) => a + b, 0) / 3 : null;
  const out = iAvg != null && vAvg != null ? (3 * vAvg * iAvg * (pf ?? 1)) / 1000 : null;
  const inn = out != null ? out + (loss ?? 0) / 1000 : null;
  const mx = Math.max(inn ?? 0, out ?? 0, 1);
  return (
    <Card title="AC power flow">
      <div className="st-flow">
        <div><span><i className="sw in" />AC in, HV</span><b>{fmt(inn)}<small>kW</small></b><u><s style={{ width: `${((inn ?? 0) / mx) * 100}%` }} className="in" /></u></div>
        <div><span><i className="sw out" />AC out, LV</span><b>{fmt(out)}<small>kW</small></b><u><s style={{ width: `${((out ?? 0) / mx) * 100}%` }} className="out" /></u></div>
        <p>{fmt(iAvg)} A · {fmt(vAvg)} V per phase · PF {fmt(pf, 2)}<br />Lost in the transformer: {loss == null ? "—" : (loss / 1000).toFixed(2)} kW</p>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- trends under the model
function Chart({ w, series, unit, y0, y1 }: { w: Win; series: { key: string; cls: string; scale?: number }[]; unit: string; y0?: number; y1?: number }) {
  const W = 360, H = 58;
  const tEnd = w.t[w.t.length - 1];
  const xNow = ((w.now - w.t[0]) / (tEnd - w.t[0] || 1)) * W;
  const vals = series.flatMap((s) => w.v[s.key].map((v) => (v == null ? null : v * (s.scale ?? 1))).filter((v): v is number => v != null));
  const lo = y0 ?? (vals.length ? Math.min(...vals) : 0), hi = y1 ?? (vals.length ? Math.max(...vals) : 1);
  const pad = (hi - lo) * 0.08 || 1;
  const a = lo - (y0 == null ? pad : 0), b = hi + (y1 == null ? pad : 0);
  const ticks = [a, (a + b) / 2, b];
  return (
    <svg viewBox={`0 0 ${W + 34} ${H + 16}`} className="st-chart" role="img" aria-label={`Around now, ${unit}`}>
      <g transform="translate(34,4)">
        {ticks.map((t) => <g key={t}><line x1="0" x2={W} y1={H - ((t - a) / (b - a)) * H} y2={H - ((t - a) / (b - a)) * H} className="g" /><text x="-4" y={H - ((t - a) / (b - a)) * H + 3} textAnchor="end">{Math.round(t)}</text></g>)}
        {series.map((s) => {
          const ys = w.v[s.key].map((v) => (v == null ? null : v * (s.scale ?? 1)));
          return (
            <g key={s.key}>
              <Path xs={w.t} ys={ys.map((v, k) => (k <= w.nowAt ? v : null))} x0={w.t[0]} x1={tEnd} y0={a} y1={b} w={W} h={H} cls={`ln ${s.cls}`} />
              <Path xs={w.t} ys={ys.map((v, k) => (k >= w.nowAt ? v : null))} x0={w.t[0]} x1={tEnd} y0={a} y1={b} w={W} h={H} cls={`ln ${s.cls} fut`} />
            </g>
          );
        })}
        <line x1={xNow} x2={xNow} y1="0" y2={H} className="now" />
        <text x="0" y={H + 12} className="ax">{w.nowAt > 20 ? "1.5 days ago" : ""}</text><text x={xNow} y={H + 12} textAnchor="middle" className="ax">now</text><text x={W} y={H + 12} textAnchor="end" className="ax">+1.5 days</text>
      </g>
    </svg>
  );
}

function Trends() {
  const w = useWindow(["OTI_C", "twin_oil_C", "twin_hs_C", "loading_pct", "load_pu", "IR", "IY", "IB"], 36, 36);
  if (!w) return null;
  const hasMeas = w.v.OTI_C.some((v) => v != null);
  const hasLoadPct = w.v.loading_pct.some((v) => v != null);
  return (
    <div className="st-trends">
      <Card title="Oil and hot spot, around now" className="wide">
        <Chart w={w} unit="°C" series={[{ key: "twin_hs_C", cls: "grey" }, { key: "twin_oil_C", cls: "twin dash" }, ...(hasMeas ? [{ key: "OTI_C", cls: "meas" }] : [])]} />
        <p className="st-legend"><i className="twin" /> top-oil twin <i className="meas" /> top-oil sensor <i className="grey" /> hot spot twin</p>
      </Card>
      <Card title="Load and phase currents, around now" className="wide">
        <Chart w={w} unit="%" y0={0} series={hasLoadPct ? [{ key: "loading_pct", cls: "ink" }] : [{ key: "load_pu", cls: "ink", scale: 100 }]} />
        <p className="st-legend"><i className="ink" /> load, % of rating</p>
      </Card>
      <Card title="Phase currents, around now" className="wide">
        <Chart w={w} unit="A" y0={0} series={[{ key: "IR", cls: "ink" }, { key: "IY", cls: "twin" }, { key: "IB", cls: "meas" }]} />
        <p className="st-legend"><i className="ink" /> R <i className="twin" /> Y <i className="meas" /> B</p>
      </Card>
    </div>
  );
}

function Bar({ label, v, unit, max, tone = "ink" }: { label: string; v: number | null; unit: string; max: number; tone?: string }) {
  return (
    <div className="st-bar">
      <span>{label}</span><b>{fmt(v, 0)}<small>{unit}</small></b>
      <u><s className={tone} style={{ width: `${Math.max(0, Math.min(100, ((v ?? 0) / max) * 100))}%` }} /></u>
    </div>
  );
}

function OilAmbient() {
  const i = usePlayerIndex();
  const r = i >= 0 ? player.row(i) : {};
  return (
    <Card title="Oil level and air">
      <div className="st-bars">
        <Bar label="Oil level" v={num(r.OLI_pct)} unit="%" max={100} tone="twin" />
        <Bar label="Humidity" v={num(r.RH_pct)} unit="%" max={100} />
        <Bar label="Ambient" v={num(r.ATI_C) ?? num(r.amb_C)} unit="°C" max={50} tone="meas" />
      </div>
    </Card>
  );
}

function Ageing() {
  const i = usePlayerIndex();
  const r = i >= 0 ? player.row(i) : {};
  const rate = num(r.aging_rate_actual) ?? num(r.aging_rate);
  // a one-row frame (Simulate's instant steady answer) has no history, so nothing has been "used so far"
  const used = (player.frames?.t.length ?? 0) > 1 ? num(r.days_aged_actual_cum) ?? num(r.days_aged_cum) : null;
  return (
    <Card title="Insulation ageing">
      <div className="st-age">
        <b className={rate != null && rate > 1.5 ? "hot" : ""}>{fmt(rate, 2)}<small>× design</small></b>
        <span>speed of wear now</span>
        <b>{fmt(used, 1)}<small>days</small></b>
        <span>of paper life used so far</span>
      </div>
    </Card>
  );
}

export function StageLeft() { return <div className="st-col"><Thermometers /><LoadDial /><OilAmbient /></div>; }
export function StageRight() { return <div className="st-col"><HealthRing /><FlowMini /><Ageing /></div>; }
export { Trends as StageTrends };
