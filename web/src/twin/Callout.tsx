// Callouts laid out like a drawing: boxes stacked in the field's left/right gutters (ordered by height, never
// overlapping), each tied to its part by a leader (dot → diagonal → shoulder). Boxes cite the sheet zone.
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { player, usePlayerIndex } from "../player/player";
import * as THREE from "three";
import { PART, type Part, type PartId } from "./parts";
import { fmt, trustOf, type FieldRef, type Trust } from "../data/fields";
import type { PartView } from "../api/client";

export interface CalloutData {
  row: Record<string, unknown> | null;
  twin: Record<string, unknown> | null;
  asset: Record<string, unknown> | null;
  otiSuspect: boolean;
  error: string | null;
}
export type Anchors = Partial<Record<PartId, { x: number; y: number }>>;

const TRUST_LABEL: Record<Trust, string> = { trusted: "trusted", suspect: "suspect", missing: "missing", estimated: "est." };
const BOX_W_MAX = 262;
const GUTTER = 14;
const GAP = 10;

// ---------------------------------------------------------------- inside the Canvas: project anchors to pixels
export function AnchorTracker({ ids, onChange }: { ids: PartId[]; onChange: (a: Anchors) => void }) {
  const { camera, size } = useThree();
  const last = useRef("");
  const v = useRef(new THREE.Vector3());
  useFrame(() => {
    const out: Anchors = {};
    for (const id of ids) {
      v.current.set(...PART[id].anchor).project(camera);
      out[id] = { x: Math.round((v.current.x * 0.5 + 0.5) * size.width), y: Math.round((-v.current.y * 0.5 + 0.5) * size.height) };
    }
    const key = JSON.stringify(out);
    if (key !== last.current) { // only when the view or the shown set changes, not every frame
      last.current = key;
      onChange(out);
    }
  });
  return null;
}

// ---------------------------------------------------------------- outside the Canvas: the layout and the boxes
function valueOf(fr: FieldRef, d: CalloutData): unknown {
  const src = fr.source === "row" ? d.row : fr.source === "twin" ? d.twin : d.asset;
  return src ? src[fr.key] : undefined;
}

function estHeight(p: Part, d: CalloutData): number {
  const roleLines = Math.ceil(p.role.length / 38);
  const rows = d.error || p.fields.length === 0 ? 2 : p.fields.length;
  return 30 + roleLines * 15 + rows * 19;
}

const ZONE_ROWS = "ABCDEF";
function zoneOf(px: number, py: number, field: DOMRect | undefined, sheet: DOMRect | undefined): string {
  if (!field || !sheet) return "";
  const gx = field.left + px - sheet.left, gy = field.top + py - sheet.top;
  const col = Math.min(8, Math.max(1, Math.floor((gx / sheet.width) * 8) + 1));
  const row = ZONE_ROWS[Math.min(5, Math.max(0, Math.floor((gy / sheet.height) * 6)))];
  return `${row}${col}`;
}

export function CalloutLayer({ shown: allShown, pinned, anchors, data, width, height, onUnpin, fieldRect, sheetRect, bubbles = {}, bubbleClass = {}, popover = false, views = {}, boxW = 300 }: {
  boxW?: number;
  popover?: boolean; // boxes open right beside the part they describe, with the part's live explanation when pinned
  views?: Partial<Record<PartId, PartView>>;
  bubbleClass?: Partial<Record<PartId, string>>;
  bubbles?: Partial<Record<PartId, string>>; // pinned parts whose detail view is open: a lettered bubble instead of a box
  shown: PartId[]; pinned: PartId[]; anchors: Anchors; data: CalloutData; width: number; height: number;
  onUnpin: (id: PartId) => void; fieldRect?: DOMRect; sheetRect?: DOMRect;
}) {
  // heights: measured after render (estimate until then), so stacked boxes never overlap
  const shown = allShown.filter((id) => !(bubbles[id] && pinned.includes(id))); // a pinned part with a detail view: bubble only
  const [measured, setMeasured] = useState<Partial<Record<PartId, number>>>({});
  const boxes = useRef(new Map<PartId, HTMLDivElement>());
  const measure = () => {
    const next: Partial<Record<PartId, number>> = {};
    for (const [id, el] of boxes.current) next[id] = el.offsetHeight;
    setMeasured((prev) =>
      Object.keys(next).some((k) => Math.abs((prev[k as PartId] ?? 0) - (next[k as PartId] ?? 0)) > 1) ? next : prev);
  };
  // re-measure whenever a box changes size (fonts finishing loading, values changing), not only on render
  const observer = useRef<ResizeObserver | null>(null);
  if (!observer.current && typeof ResizeObserver !== "undefined") observer.current = new ResizeObserver(() => measure());
  useLayoutEffect(measure);
  useEffect(() => () => observer.current?.disconnect(), []);
  const BOX_W = popover ? boxW : Math.round(Math.min(BOX_W_MAX, Math.max(196, width * 0.25))); // narrower boxes on laptop screens
  const placed: { id: PartId; x: number; y: number; h: number; side: "left" | "right" }[] = [];
  // compact mode per gutter: hide the role line when the full-size stack can't fit (decided from estimates,
  // so it can't oscillate as measured heights change)
  const compact = { left: false, right: false };
  for (const side of ["left", "right"] as const) {
    const full = shown.filter((id) => PART[id].side === side).reduce((s, id) => s + estHeight(PART[id], data) + GAP, 0);
    compact[side] = full > height - 2 * GUTTER;
  }
  if (popover) {
    // each box opens beside its own part (right of it, or left when there is no room), kept inside the field
    const items = shown.filter((id) => anchors[id]).map((id) => {
      const a = anchors[id]!;
      const side: "left" | "right" = a.x + 24 + BOX_W + GUTTER < width ? "right" : "left";
      const h = measured[id] ?? estHeight(PART[id], data) + (pinned.includes(id) ? 220 : 0);
      return { id, side, h, a };
    }).sort((p, q) => p.a.y - q.a.y);
    let floor = GUTTER;
    for (const it of items) {
      const want = Math.min(Math.max(floor, it.a.y - 20), Math.max(GUTTER, height - it.h - GUTTER));
      placed.push({ id: it.id, x: it.side === "right" ? it.a.x + 26 : it.a.x - 26 - BOX_W, y: want, h: it.h, side: it.side });
      floor = want + it.h + GAP;
    }
  } else
  for (const side of ["left", "right"] as const) {
    const items = shown.filter((id) => PART[id].side === side && anchors[id])
      .map((id) => ({ id, h: measured[id] ?? estHeight(PART[id], data), want: anchors[id]!.y - 24 }))
      .sort((a, b) => a.want - b.want);
    // pass 1, top-down: each box as close to its part as possible without overlapping the one above
    const ys: number[] = [];
    let cursor = GUTTER;
    for (const it of items) {
      const y = Math.max(cursor, it.want);
      ys.push(y);
      cursor = y + it.h + GAP;
    }
    // pass 2, bottom-up: if the stack runs past the field, push it back up. Only when the whole stack fits;
    // otherwise keep pass 1 (no overlap, the gutter scrolls). Boxes never overlap.
    const total = items.reduce((s, it) => s + it.h + GAP, 0) - GAP;
    if (total <= height - 2 * GUTTER) {
      let floor = height - GUTTER;
      for (let i = items.length - 1; i >= 0; i--) {
        ys[i] = Math.min(ys[i], floor - items[i].h);
        floor = ys[i] - GAP;
      }
    }
    items.forEach((it, i) =>
      placed.push({ id: it.id, x: side === "left" ? GUTTER : width - GUTTER - BOX_W, y: ys[i], h: it.h, side }));
  }
  return (
    <div className="callout-layer">
      <svg className="leaders" width={width} height={height} aria-hidden="true">
        {(Object.keys(bubbles) as PartId[]).filter((id) => anchors[id]).map((id) => {
          const a = anchors[id]!;
          const label = bubbles[id]!;
          const w = Math.max(20, 7 * label.length + 10); // one character: a circle; several numbers: a capsule
          return (
            <g key={`b-${id}`} className={`detail-bubble ${bubbleClass[id] ?? ""}`}>
              <polyline points={`${a.x},${a.y} ${a.x + 16},${a.y - 16}`} />
              <circle cx={a.x} cy={a.y} r={2.8} />
              <rect x={a.x + 15} y={a.y - 35} width={w} height={20} rx={10} className="ring" />
              <text x={a.x + 15 + w / 2} y={a.y - 21} textAnchor="middle">{label}</text>
            </g>
          );
        })}
        {placed.map(({ id, x, y, side }) => {
          const a = anchors[id]!;
          const edge = side === "left" ? x + BOX_W : x;
          const ty = y + 13;
          const shoulder = popover ? (side === "left" ? edge + 8 : edge - 8) : side === "left" ? edge + 22 : edge - 22;
          return (
            <g key={id}>
              <polyline points={`${a.x},${a.y} ${shoulder},${ty} ${edge},${ty}`} />
              <circle cx={a.x} cy={a.y} r={2.8} />
            </g>
          );
        })}
      </svg>
      {placed.map(({ id, x, y, side }) => {
        const part = PART[id];
        const isPinned = pinned.includes(id);
        const dq = (data.row?.["dq_flags"] as string | undefined) ?? "";
        const a = anchors[id]!;
        return (
          <div key={id} ref={(el) => {
              const prev = boxes.current.get(id);
              if (prev && prev !== el) observer.current?.unobserve(prev);
              if (el) { boxes.current.set(id, el); observer.current?.observe(el); } else boxes.current.delete(id);
            }}
            className={`callout callout-${side}${isPinned ? " pinned" : ""}${compact[side] ? " compact" : ""}${BOX_W < 240 ? " narrow" : ""}`}
            style={{ left: x, top: y, width: BOX_W }} role="note" aria-label={part.name}>
            <div className="callout-head">
              <span className="callout-name">{part.name}</span>
              <span className="callout-zone" title="Drawing zone">{zoneOf(a.x, a.y, fieldRect, sheetRect)}</span>
              {isPinned && <button className="unpin" onClick={() => onUnpin(id)} aria-label={`Unpin ${part.name}`}>×</button>}
            </div>
            <p className="callout-role">{part.role}</p>
            {popover && isPinned && <Explain view={views[id]} big={boxW > 340} />}
            {popover && isPinned && views[id] ? null : data.error ? (
              <p className="callout-note">{data.error}</p>
            ) : part.fields.length === 0 ? (
              <p className="callout-note">{part.note}</p>
            ) : (
              <table className="callout-values">
                <tbody>
                  {part.fields.map((fr) => {
                    const v = valueOf(fr, data);
                    const trust = fr.kind === "measured" ? trustOf(fr.key, v, dq, data.otiSuspect) : null;
                    return (
                      <tr key={`${fr.source}.${fr.key}`} className={`k-${fr.kind}`}>
                        <td className="lbl">{fr.label}{fr.kind === "twin" && <span className="who"> twin</span>}</td>
                        <td className="num">{fmt(v, fr.digits ?? 1)}</td>
                        <td className="unit">{fr.unit}{fr.estimated && <span className="est"> est.</span>}</td>
                        <td className="trust">{trust && <span className={`trust-${trust}`}>{TRUST_LABEL[trust]}</span>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        );
      })}
    </div>
  );
}

// 3-day history of one quantity from the replay frames: a filled trace with its range and the value now.
function Trace({ k, unit }: { k: string; unit: string }) {
  const i = usePlayerIndex();
  const f = player.frames;
  const d = useMemo(() => {
    if (!f || i < 0 || !f.cols[k]) return null;
    const t1 = f.t[i], t0 = t1 - 3 * 86_400_000;
    let j = i;
    while (j > 0 && f.t[j - 1] >= t0) j--;
    const pts: [number, number][] = [];
    for (let n = j; n <= i; n += Math.max(1, Math.floor((i - j) / 90))) { const v = f.cols[k][n]; if (typeof v === "number") pts.push([f.t[n], v]); }
    if (pts.length < 3) return null;
    let lo = Infinity, hi = -Infinity;
    for (const [, v] of pts) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    const span = hi - lo || 1, W = 150, H = 34;
    const xy = pts.map(([t, v]) => [((t - t0) / (t1 - t0)) * W, H - 3 - ((v - lo) / span) * (H - 6)] as const);
    const line = xy.map(([x, y], n) => `${n ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join("");
    return { line, area: `${line}L${xy[xy.length - 1][0].toFixed(1)} ${H}L${xy[0][0].toFixed(1)} ${H}Z`, lo, hi, last: xy[xy.length - 1] };
  }, [f, i, k]);
  if (!d) return <span className="trace-none" />;
  return (
    <span className="trace" title={`3 days: ${d.lo.toFixed(1)} to ${d.hi.toFixed(1)} ${unit}`}>
      <svg viewBox="0 0 150 34" preserveAspectRatio="none" aria-hidden="true"><path d={d.area} className="fill" /><path d={d.line} className="ln" /><circle cx={d.last[0]} cy={d.last[1]} r={2.6} /></svg>
      <small>{d.lo.toFixed(0)}–{d.hi.toFixed(0)}</small>
    </span>
  );
}

// How the part is doing, in words; its live numbers with a 3-day trace each; the governing equations with today's values.
function Explain({ view, big }: { view: PartView | undefined; big: boolean }) {
  if (!view) return <p className="callout-note">Reading the twin…</p>;
  const rank = (s: string) => (s === "critical" ? 2 : s === "warning" ? 1 : 0);
  const worst = [...view.alerts].sort((p, q) => rank(q.severity) - rank(p.severity))[0];
  const eqs = big ? view.equations : view.equations.slice(0, 1);
  return (
    <div className="pop-explain">
      <p className={"pop-status " + (worst ? `sev-${worst.severity}` : "ok")}>
        <b>{worst ? (worst.severity === "critical" ? "Needs attention" : "Watch") : "Healthy"}</b>
        {worst ? worst.explanation : "No findings on this part in the last 24 h."}
      </p>
      {view.quantities.length > 0 && (
        <table className="pop-q">
          <tbody>
            {view.quantities.map((q) => (
              <tr key={q.key + q.label} className={`k-${q.kind}`}>
                <th scope="row">{q.label}{q.kind === "twin" && <span className="who"> twin</span>}</th>
                <td className="num">{q.value === null ? "—" : q.value.toFixed(q.digits)}<small> {q.unit}{q.estimated ? " est." : ""}</small></td>
                <td className="tr"><Trace k={q.key} unit={q.unit} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {eqs.map((eq) => (
        <section key={eq.name} className="pop-eq">
          <h4>{eq.name}{eq.estimated && <span className="who"> est.</span>}</h4>
          <p className="sym">{eq.symbolic}</p>
          <p className="live">{eq.substituted ?? "—"}</p>
          {big && (
            <table className="terms"><tbody>{eq.terms.map((t) => (
              <tr key={t.symbol}><th>{t.symbol}</th><td className="num">{t.value === null ? "—" : t.value.toFixed(t.digits)} <small>{t.unit}</small></td><td className="mean">{t.meaning}</td></tr>
            ))}</tbody></table>
          )}
          {big && eq.note && <p className="eq-note">{eq.note}</p>}
        </section>
      ))}
      {!big && view.equations.length > 1 && <p className="pop-more">{view.equations.length - 1} more equation{view.equations.length > 2 ? "s" : ""} in the expanded view</p>}
      {view.alerts.length > 1 && (
        <ul className="pop-find">{view.alerts.slice(0, big ? 6 : 2).map((a) => <li key={a.id} className={`sev-${a.severity}`}>{a.explanation}</li>)}</ul>
      )}
      {view.tests[0] && <p className="pop-test"><b>Suggested test</b> {view.tests[0]}</p>}
    </div>
  );
}
