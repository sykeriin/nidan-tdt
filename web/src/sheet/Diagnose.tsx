// DIAGNOSE mode: findings up to the replay cursor (GET /findings), grouped under CPRI's three causes
// (Overloading, Insulation, Short circuit) and then supply, oil and sensor findings. Each finding is numbered;
// the same number is drawn on the parts it concerns. Through-fault stress is a fill bar toward the %X test rule.
import { useEffect, useRef } from "react";
import type { Finding, Findings } from "../api/client";
import { PART, type PartId } from "../twin/parts";

// plain names for alert types (presentation text)
const TYPE: Record<string, string> = {
  loading_high: "Load above the planning limit", overcurrent: "Overcurrent", hot_spot_high: "Hot-spot above 98 °C",
  top_oil_high: "Top-oil above limit", ageing_rate_high: "Paper ageing faster than normal",
  residual_drift: "Oil hotter than physics predicts", current_unbalance: "Phase currents unbalanced",
  voltage_unbalance: "Phase voltages unbalanced", voltage_high: "Voltage high", voltage_low: "Voltage low",
  oil_low: "Oil level low", oil_leak: "Oil level falling (leak)", oil_theft: "Oil level step (theft or tampering)",
  through_fault: "Through-fault", through_fault_stress: "Through-fault stress limit reached",
  jump_sensor: "Sensor jumped", range_sensor: "Sensor out of range", stuck_sensor: "Sensor stuck",
  dead_channel: "Channel dead", drift_sensor: "Sensor drifting", implausible_sensor: "Reading physics can't explain",
};
const URGENCY: Record<string, string> = { immediate: "now", "24h": "within 24 h", "7d": "within 7 days", next_scheduled: "next scheduled outage" };
const THREE = ["Overloading", "Insulation", "Short circuit"];

export const findingLabel = (f: Finding) => TYPE[f.type] ?? f.type.replace(/_/g, " ");

/** Part → numbers of the findings drawn on it, and the worst severity there (for the marker stamp). */
export function findingMarks(fs: Findings | undefined) {
  const marks: Partial<Record<PartId, { nums: number[]; sev: string }>> = {};
  const rank = (s: string) => ({ critical: 0, warning: 1, info: 2 } as Record<string, number>)[s] ?? 3;
  (fs?.findings ?? []).forEach((f, n) => {
    for (const p of f.parts as PartId[]) {
      if (!(p in PART)) continue;
      const m = (marks[p] ??= { nums: [], sev: "sensor" }); // "sensor" until an asset finding lands here
      m.nums.push(n + 1);
      if (f.origin !== "sensor" && (m.sev === "sensor" || rank(f.severity) < rank(m.sev))) m.sev = f.severity;
    }
  });
  return marks;
}

export function DiagnosePanel({ data, loading, error, focus, onFocus }: {
  data: Findings | undefined; loading: boolean; error: string | null; focus: PartId | null;
  onFocus: (parts: PartId[] | null) => void;
}) {
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => { // clicking a part scrolls to its first finding
    if (!focus || !list.current) return;
    list.current.querySelector(`[data-parts~="${focus}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [focus]);
  const fs = data?.findings ?? [];
  const groups = [...THREE, ...(data?.causes ?? []).filter((c) => !THREE.includes(c))];
  const s = data?.stress;
  return (
    <aside className="detail diagnose" aria-label="Findings">
      <div className="detail-head"><h2>Findings</h2><span className="dg-count">{fs.length ? `${fs.length} up to the cursor` : ""}</span></div>
      {error && <p className="field-error">{error}</p>}
      <div className="detail-scroll" ref={list}>
        {!data && loading && <p className="field-note">Reading the findings…</p>}
        {groups.map((g) => {
          const items = fs.map((f, n) => ({ f, n })).filter(({ f }) => f.cause === g);
          if (!THREE.includes(g) && !items.length) return null;
          return (
            <section key={g} className="dg-group">
              <h3>{g}{THREE.includes(g) && <span className="dg-cpri">CPRI cause</span>}</h3>
              {!items.length && <p className="dg-none">No finding so far.</p>}
              {items.map(({ f, n }) => (
                <article key={f.id} className={`dg-item sev-${f.severity} org-${f.origin}${focus && f.parts.includes(focus) ? " focus" : ""}`}
                  data-parts={f.parts.join(" ")} tabIndex={0}
                  onMouseEnter={() => onFocus(f.parts as PartId[])} onMouseLeave={() => onFocus(null)}
                  onFocus={() => onFocus(f.parts as PartId[])} onBlur={() => onFocus(null)}>
                  <header>
                    <span className="dg-num">{n + 1}</span>
                    <span className="dg-title">{findingLabel(f)}</span>
                    <span className="dg-sev">{f.origin === "sensor" ? "sensor" : f.indicative ? "indicative" : f.severity}</span>
                  </header>
                  <p className="dg-expl">{f.explanation}</p>
                  <p className="dg-meta">on {f.parts.map((p) => PART[p as PartId]?.name ?? p).join(", ") || "the asset"}
                    {f.count > 1 ? `; ${f.count} times, last ${f.last.slice(5, 16).replace("T", " ")}` : `; ${f.last.slice(5, 16).replace("T", " ")}`}</p>
                  {f.recommendation?.test && (
                    <p className="dg-test"><b>Test:</b> {f.recommendation.test}
                      <span className="dg-urg"> {URGENCY[f.recommendation.urgency] ?? f.recommendation.urgency}</span>
                      {f.recommendation.standard_ref && <span className="dg-ref"> ({f.recommendation.standard_ref})</span>}</p>
                  )}
                </article>
              ))}
              {g === "Short circuit" && s && <Stress s={s} />}
            </section>
          );
        })}
      </div>
    </aside>
  );
}

function Stress({ s }: { s: Findings["stress"] }) {
  const frac = s.triggered ? 1 : Math.min(1, s.qualifying / Math.max(1, s.moderate_limit));
  return (
    <figure className="dg-stress" aria-label="Through-fault stress">
      <figcaption>Through-fault stress <span>toward the %X impedance test</span></figcaption>
      <div className="dg-bar"><span style={{ width: `${frac * 100}%` }} />
        {Array.from({ length: s.moderate_limit - 1 }, (_, k) => <i key={k} style={{ left: `${((k + 1) / s.moderate_limit) * 100}%` }} />)}
      </div>
      <p>{s.qualifying} of {s.moderate_limit} events ≥ {s.moderate_pu} pu{s.severe_seen ? `, one ≥ ${s.severe_pu} pu (severe)` : ""}; I²t {s.cum_i2t_pu2s.toFixed(1)} pu²·s
        {s.triggered && <b className="dg-trig"> %X test due</b>}</p>
      {s.last_event && <p className="dg-last">last {s.last_event.timestamp.slice(5, 16).replace("T", " ")}: {s.last_event.peak_pu.toFixed(1)} pu, {s.last_event.duration_ms.toFixed(0)} ms ({s.last_event.class})</p>}
      {!s.events && <p className="dg-last">No through-fault events recorded.</p>}
    </figure>
  );
}
