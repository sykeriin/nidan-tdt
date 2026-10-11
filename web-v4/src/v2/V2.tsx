// Interface v2: the same twin and data, shown as a few large visuals instead of schedules and drawing chrome.
// Left rail: health ring and the four numbers that matter. Right rail: what is going on, in a sentence, with the evidence bars.
import { useState, type ReactNode } from "react";
import { useBrief } from "../api/client";
import type { Cell } from "../player/player";
import { LAYERS, type LayerId, type Layers } from "../twin/layers";

type Row = Record<string, Cell> | null;
const n = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const f = (v: number | null, d = 0) => (v == null ? "—" : v.toFixed(d));

const BAND: Record<string, string> = { green: "var(--ok)", yellow: "var(--warn)", red: "var(--bad)" };

function Ring({ score, band }: { score: number | null; band: string | null }) {
  const R = 52, C = 2 * Math.PI * R, v = Math.max(0, Math.min(100, score ?? 0));
  const colour = (band && BAND[band.toLowerCase()]) || "var(--ink-3)";
  return (
    <div className="v2-ring" role="img" aria-label={`Health index ${score == null ? "unavailable" : Math.round(score)} of 100`}>
      <svg viewBox="0 0 128 128">
        <circle cx="64" cy="64" r={R} className="track" />
        <circle cx="64" cy="64" r={R} className="arc" style={{ stroke: colour, strokeDasharray: `${(v / 100) * C} ${C}` }} transform="rotate(-90 64 64)" />
      </svg>
      <div className="v2-ring-n"><b>{score == null ? "—" : Math.round(score)}</b><span>health</span></div>
    </div>
  );
}

/** A horizontal gauge: value on a scale with the limit marked. */
function Gauge({ label, value, unit, min, max, marks, tone, sub }: {
  label: string; value: number | null; unit: string; min: number; max: number; marks?: { at: number; label: string }[]; tone: "twin" | "measured" | "ink"; sub?: ReactNode;
}) {
  const pos = (x: number) => `${Math.max(0, Math.min(100, ((x - min) / (max - min)) * 100))}%`;
  return (
    <div className={`v2-tile tone-${tone}`}>
      <div className="v2-tile-top"><span>{label}</span><b>{f(value, 0)}<em>{unit}</em></b></div>
      <div className="v2-gauge">
        <i style={{ width: value == null ? 0 : pos(value) }} />
        {marks?.map((m) => <u key={m.label} style={{ left: pos(m.at) }} title={m.label} />)}
      </div>
      {sub && <small>{sub}</small>}
    </div>
  );
}

export function V2Left({ row, simulated }: { row: Row; simulated: boolean }) {
  const r = row ?? {};
  const hs = n(r.WTI_C) ?? n(r.twin_hs_C), twinOil = n(r.twin_oil_C), oil = n(r.OTI_C) ?? twinOil;
  const gap = n(r.residual_oil_C), load = n(r.load_pu), rate = n(r.aging_rate_actual) ?? n(r.aging_rate);
  return (
    <div className="v2-left">
      <div className="v2-card v2-health">
        <Ring score={n(r.health_score)} band={typeof r.health_band === "string" ? r.health_band : null} />
        <div>
          <h3>{String(r.health_band).toLowerCase() === "red" ? "Needs attention" : String(r.health_band).toLowerCase() === "yellow" ? "Watch" : row ? "Healthy" : "No data"}</h3>
          <p>{simulated ? "Simulated data" : "Health index, 0 to 100"}</p>
        </div>
      </div>
      <Gauge label="Hot spot" value={hs} unit="°C" min={20} max={140} tone="twin" marks={[{ at: 98, label: "98 ageing reference" }, { at: 120, label: "120 limit" }]}
        sub={<>Reference 98 °C, limit 120 °C</>} />
      <Gauge label="Top oil" value={oil} unit="°C" min={20} max={110} tone={n(r.OTI_C) != null ? "measured" : "twin"} marks={[{ at: 85, label: "alarm" }, { at: 95, label: "trip" }]}
        sub={gap != null ? <>{gap >= 0 ? "+" : ""}{gap.toFixed(1)} K against the physics</> : "Twin estimate"} />
      <Gauge label="Load" value={load == null ? null : load * 100} unit="%" min={0} max={140} tone="ink" marks={[{ at: 100, label: "rating" }]} sub="of nameplate rating" />
      <div className="v2-tile tone-ink">
        <div className="v2-tile-top"><span>Ageing speed</span><b>{f(rate, 2)}<em>× design</em></b></div>
        <small>{rate == null ? "" : rate > 1.5 ? "Insulation is wearing faster than designed" : "At or below the designed pace"}</small>
      </div>
    </div>
  );
}

export function V2Right({ dataset, iso, enabled, sim }: { dataset: string; iso: string | null; enabled: boolean; sim: boolean }) {
  const q = useBrief(dataset, iso, enabled);
  const b = q.data;
  const level = b?.level ?? "nodata";
  const shown = (b?.diagnosis ?? []).filter((d) => d.observable && d.evidence >= 0.15).slice(0, 3);
  return (
    <div className="v2-right">
      <div className={`v2-card v2-status lv-${level}`}>
        <span className="v2-dot" aria-hidden />
        <p>{sim ? "What if: the twin shows where temperatures settle at the load, ambient and cooling set below." : !enabled ? "This dataset has no time axis, so there is nothing to follow." : b ? b.sentence : "Reading the transformer…"}</p>
      </div>
      {shown.length > 0 && (
        <div className="v2-card">
          <h3>What the evidence points to</h3>
          {shown.map((d) => (
            <div className="v2-ev" key={d.fault}>
              <span>{d.label}</span><b>{Math.round(d.share * 100)}%</b>
              <i><u style={{ width: `${Math.max(4, d.share * 100)}%` }} /></i>
            </div>
          ))}
        </div>
      )}
      {b?.advice && b.advice.actions.length > 0 && (
        <div className="v2-card">
          <h3>Next step <em className={`v2-prio p-${b.advice.priority}`}>{b.advice.priority}</em></h3>
          <p className="v2-act">{b.advice.actions[0].action}</p>
          <small>{b.advice.schedule}</small>
        </div>
      )}
      {b?.kpis.headroom && (
        <div className="v2-card v2-mini">
          <div><b>{Math.round(b.kpis.headroom.pu * 100)}%</b><span>spare capacity</span></div>
          <div><b>{b.kpis.time_to_limit?.status === "reaches_limit" ? `${f(b.kpis.time_to_limit.hours ?? null, 1)} h` : b.kpis.time_to_limit?.status === "already_reached" ? "now" : "none"}</b><span>to a limit</span></div>
        </div>
      )}
    </div>
  );
}

export function V2Layers({ layers, onToggle }: { layers: Layers; onToggle: (id: LayerId) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="v2-layers">
      <button className="v2-pill" aria-expanded={open} onClick={() => setOpen(!open)}>Layers</button>
      {open && (
        <div className="v2-pop" role="group" aria-label="Physics layers">
          {LAYERS.map((l) => (
            <label key={l.id} title={l.physics}><input type="checkbox" checked={layers[l.id]} onChange={() => onToggle(l.id)} /> {l.label}</label>
          ))}
        </div>
      )}
    </div>
  );
}
