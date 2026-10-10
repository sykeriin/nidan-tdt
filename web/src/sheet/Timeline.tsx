// The timeline, drawn as a ruler: measured vs twin top-oil trace, alert / through-fault / fault-onset marks,
// a cursor that follows the replay clock (DOM writes, not React state), play/pause/speeds, drag to scrub.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { player, usePlayerTick, type Frames } from "../player/player";
import type { Alert } from "../api/client";

const SPEEDS = [60, 240, 1440, 8640];
const speedLabel = (s: number) => (s === 8640 ? "1 day/10 s" : `${s}×`);
const TRACE_H = 46;
const LANE_H = 14;

// callback ref: the track only exists once frames have loaded, so a mount-time effect would miss it
function useWidth<T extends HTMLElement>() {
  const [el, setEl] = useState<T | null>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    if (!el) return;
    setW(el.clientWidth);
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return [setEl, w] as const;
}

/** Per-pixel min/max decimation of a series for drawing only (17k Kaggle samples into ~1000 px). */
function tracePoints(f: Frames, key: string, w: number, lo: number, hi: number): string {
  const col = f.cols[key];
  if (!col || w <= 0) return "";
  const t0 = f.t[0], span = f.t[f.t.length - 1] - t0 || 1;
  const yOf = (v: number) => TRACE_H - 2 - ((v - lo) / (hi - lo || 1)) * (TRACE_H - 6);
  const px = Math.round(w);
  const mn = new Array(px).fill(Infinity), mx = new Array(px).fill(-Infinity);
  for (let i = 0; i < col.length; i++) {
    const v = col[i];
    if (typeof v !== "number") continue;
    const x = Math.min(px - 1, Math.floor(((f.t[i] - t0) / span) * px));
    if (v < mn[x]) mn[x] = v;
    if (v > mx[x]) mx[x] = v;
  }
  const pts: string[] = [];
  for (let x = 0; x < px; x++) {
    if (mn[x] === Infinity) continue;
    pts.push(`${x},${yOf(mn[x]).toFixed(1)}`);
    if (mx[x] !== mn[x]) pts.push(`${x},${yOf(mx[x]).toFixed(1)}`);
  }
  return pts.join(" ");
}

export function Timeline({ frames, alerts, events, meterOnly }: {
  frames: Frames | null;
  alerts: Alert[];
  events: Record<string, unknown>[];
  meterOnly: boolean;
}) {
  usePlayerTick(); // play/pause/speed buttons
  const [wrap, w] = useWidth<HTMLDivElement>();
  const cursor = useRef<HTMLDivElement>(null);
  const readout = useRef<HTMLSpanElement>(null);

  // cursor + time readout follow the clock without React renders
  useEffect(() => player.onTick(() => {
    if (!frames || !cursor.current) return;
    const x = ((player.t - frames.t[0]) / (frames.t[frames.t.length - 1] - frames.t[0] || 1)) * w;
    cursor.current.style.transform = `translateX(${x}px)`;
    if (readout.current) readout.current.textContent = frames.iso[Math.max(0, player.index)]?.replace("T", " ").slice(0, 16) ?? "";
  }), [frames, w]);
  useEffect(() => { player.seek(player.t); }, [w]); // place the cursor after layout

  const { meas, twin, lo, hi } = useMemo(() => {
    if (!frames) return { meas: "", twin: "", lo: 0, hi: 1 };
    const vals = [...(frames.cols["OTI_C"] ?? []), ...(frames.cols["twin_oil_C"] ?? [])].filter((v): v is number => typeof v === "number");
    let lo = Infinity, hi = -Infinity;
    for (const v of vals) { if (v < lo) lo = v; if (v > hi) hi = v; }
    if (!vals.length) { lo = 0; hi = 1; }
    lo = Math.floor(lo / 10) * 10; hi = Math.ceil(hi / 10) * 10;
    return { meas: meterOnly ? "" : tracePoints(frames, "OTI_C", w, lo, hi), twin: tracePoints(frames, "twin_oil_C", w, lo, hi), lo, hi };
  }, [frames, w, meterOnly]);

  if (!frames) return <div className="timeline empty">No time axis for this dataset: it is a set of records, not a time series.</div>;
  const t0 = frames.t[0], t1 = frames.t[frames.t.length - 1], span = t1 - t0 || 1;
  const xOf = (iso: string) => ((Date.parse(iso) - t0) / span) * w;
  const days = Math.round(span / 86_400_000);
  const step = days > 60 ? 7 : 1;
  const ticks: number[] = [];
  for (let d = 0; d <= days; d += step) ticks.push(t0 + d * 86_400_000);
  const gt = frames.cols["gt_fault"];
  const onsetIdx = gt ? gt.findIndex((v) => v === 1) : -1;

  const seekFromPointer = (e: React.PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    player.seek(t0 + ((e.clientX - r.left) / r.width) * span);
  };

  return (
    <div className="timeline">
      <div className="tl-controls">
        <button className="tl-play" onClick={() => (player.playing ? player.pause() : player.play())} aria-pressed={player.playing}>
          {player.playing ? "Pause" : "Play"}
        </button>
        {SPEEDS.map((s) => (
          <button key={s} className={player.speed === s ? "on" : ""} aria-pressed={player.speed === s} onClick={() => player.setSpeed(s)}>
            {speedLabel(s)}
          </button>
        ))}
        <span className="tl-readout" ref={readout} />
        <span className="tl-legend">
          {!meterOnly && <><i className="sw meas" /> top-oil measured</>} <i className="sw twin" /> top-oil twin
          <span className="tl-scale">{lo}–{hi} °C</span>
        </span>
      </div>
      <div className="tl-track" ref={wrap}
        onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); seekFromPointer(e); }}
        onPointerMove={(e) => { if (e.buttons === 1) seekFromPointer(e); }}
        role="slider" aria-label="Replay position" aria-valuemin={0} aria-valuemax={100} tabIndex={0}
        aria-valuenow={Math.round(((player.t - t0) / span) * 100)}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") player.seek(player.t + 3_600_000 * (e.shiftKey ? 24 : 1));
          if (e.key === "ArrowLeft") player.seek(player.t - 3_600_000 * (e.shiftKey ? 24 : 1));
          if (e.key === " ") { e.preventDefault(); player.playing ? player.pause() : player.play(); }
        }}>
        <svg width={w} height={TRACE_H + LANE_H + 22} aria-hidden="true">
          <polyline className="trace twin" points={twin} transform="translate(0,0)" />
          <polyline className="trace meas" points={meas} />
          <g transform={`translate(0,${TRACE_H + 2})`}>
            {onsetIdx >= 0 && (
              <g className="mk-onset" transform={`translate(${xOf(frames.iso[onsetIdx])},0)`}>
                <line y1={-TRACE_H} y2={LANE_H} /><path d="M0 -44 h82 l-5 5 l5 5 h-82 z" />
                <text x={3} y={-35}>fault injected</text>
              </g>
            )}
            {alerts.map((a) => (
              <path key={a.id} transform={`translate(${xOf(a.timestamp)},2)`}
                className={`mk-alert ${a.severity} ${a.origin}`} d={a.origin === "sensor" ? "M-3 0 h6 v6 h-6 z" : "M0 0 l4 7 h-8 z"}>
                <title>{`${a.type} (${a.severity}, ${a.origin}) ${a.timestamp}`}</title>
              </path>
            ))}
            {events.map((e, k) => (
              <path key={k} transform={`translate(${xOf(String(e.timestamp))},0)`} className="mk-event" d="M-3 0 l4 4 l-3 2 l4 5">
                <title>{`through-fault ${e.peak_pu} pu, ${e.duration_ms} ms`}</title>
              </path>
            ))}
          </g>
          <g transform={`translate(0,${TRACE_H + LANE_H + 4})`} className="ruler-axis">
            <line x1={0} x2={w} y1={0} y2={0} />
            {ticks.map((t, k) => {
              const x = ((t - t0) / span) * w;
              const major = k % 5 === 0;
              return (
                <g key={t} transform={`translate(${x},0)`}>
                  <line y1={0} y2={major ? 7 : 4} />
                  {major && <text y={17} textAnchor="middle">{new Date(t).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}</text>}
                </g>
              );
            })}
          </g>
        </svg>
        <div className="tl-cursor" ref={cursor} />
      </div>
    </div>
  );
}
