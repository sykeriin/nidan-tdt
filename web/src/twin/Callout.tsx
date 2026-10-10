// Callouts laid out like a drawing: boxes stacked in the field's left/right gutters (ordered by height, never
// overlapping), each tied to its part by a leader (dot → diagonal → shoulder). Boxes cite the sheet zone.
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import * as THREE from "three";
import { PART, type Part, type PartId } from "./parts";
import { fmt, trustOf, type FieldRef, type Trust } from "../data/fields";

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

export function CalloutLayer({ shown: allShown, pinned, anchors, data, width, height, onUnpin, fieldRect, sheetRect, bubbles = {} }: {
  bubbles?: Partial<Record<PartId, string>>; // pinned parts whose detail view is open: a lettered bubble instead of a box
  shown: PartId[]; pinned: PartId[]; anchors: Anchors; data: CalloutData; width: number; height: number;
  onUnpin: (id: PartId) => void; fieldRect?: DOMRect; sheetRect?: DOMRect;
}) {
  // heights: measured after render (estimate until then), so stacked boxes never overlap
  const shown = allShown.filter((id) => !bubbles[id]);
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
  const BOX_W = Math.round(Math.min(BOX_W_MAX, Math.max(196, width * 0.25))); // narrower boxes on laptop screens
  const placed: { id: PartId; x: number; y: number; h: number; side: "left" | "right" }[] = [];
  // compact mode per gutter: hide the role line when the full-size stack can't fit (decided from estimates,
  // so it can't oscillate as measured heights change)
  const compact = { left: false, right: false };
  for (const side of ["left", "right"] as const) {
    const full = shown.filter((id) => PART[id].side === side).reduce((s, id) => s + estHeight(PART[id], data) + GAP, 0);
    compact[side] = full > height - 2 * GUTTER;
  }
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
          return (
            <g key={`b-${id}`} className="detail-bubble">
              <polyline points={`${a.x},${a.y} ${a.x + 16},${a.y - 16}`} />
              <circle cx={a.x} cy={a.y} r={2.8} />
              <circle cx={a.x + 25} cy={a.y - 25} r={10} className="ring" />
              <text x={a.x + 25} y={a.y - 21} textAnchor="middle">{bubbles[id]}</text>
            </g>
          );
        })}
        {placed.map(({ id, x, y, side }) => {
          const a = anchors[id]!;
          const edge = side === "left" ? x + BOX_W : x;
          const ty = y + 13;
          const shoulder = side === "left" ? edge + 22 : edge - 22;
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
            {data.error ? (
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
