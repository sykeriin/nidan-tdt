// Drawing-sheet chrome: frame with zone references, sheet tabs, schedules, timeline ruler, title block.
import type { ReactNode } from "react";
import { fmt, trustOf, type Trust } from "../data/fields";
import type { Run } from "../api/client";
import type { Cell } from "../player/player";

const COLS = 8;
const ROWS = ["A", "B", "C", "D", "E", "F"];

export function Frame() {
  return (
    <div className="frame" aria-hidden="true">
      <div className="zones zones-top">{Array.from({ length: COLS }, (_, i) => <span key={i}>{i + 1}</span>)}</div>
      <div className="zones zones-bottom">{Array.from({ length: COLS }, (_, i) => <span key={i}>{i + 1}</span>)}</div>
      <div className="zones zones-left">{ROWS.map((r) => <span key={r}>{r}</span>)}</div>
      <div className="zones zones-right">{ROWS.map((r) => <span key={r}>{r}</span>)}</div>
    </div>
  );
}

export type TwinMode = "mirror" | "simulate" | "diagnose";
const MODES: { id: TwinMode; label: string; hint: string; ready: boolean }[] = [
  { id: "mirror", label: "Mirror", hint: "The twin follows the data", ready: true },
  { id: "simulate", label: "Simulate", hint: "What-if: change load, ambient, cooling", ready: false },
  { id: "diagnose", label: "Diagnose", hint: "Findings shown on the parts", ready: false },
];

export function SheetTabs({ mode, onMode }: { mode: TwinMode; onMode: (m: TwinMode) => void }) {
  return (
    <nav className="tabs" aria-label="Twin mode">
      {MODES.map((m) => (
        <button key={m.id} className={`tab${mode === m.id ? " on" : ""}`} disabled={!m.ready}
          aria-pressed={mode === m.id} title={m.ready ? m.hint : `${m.hint} (not built yet)`} onClick={() => onMode(m.id)}>
          <span className="tab-label">{m.label}</span>
          <span className="tab-hint">{m.ready ? m.hint : "not built yet"}</span>
        </button>
      ))}
    </nav>
  );
}

export function SectionToggle({ cut, onCut }: { cut: boolean; onCut: (c: boolean) => void }) {
  return (
    <button className={`section-toggle${cut ? " on" : ""}`} onClick={() => onCut(!cut)} aria-pressed={cut}>
      <svg width="74" height="22" viewBox="0 0 74 22" aria-hidden="true">
        <text x="2" y="15">A</text>
        <path d="M14 11 H60" className="cutline" />
        <path d="M14 11 v-7 l-4 4 M60 11 v-7 l4 4" className="arrows" />
        <text x="64" y="15">A</text>
      </svg>
      <span>{cut ? "Section A–A: tank cut open" : "Section A–A: tank closed"}</span>
    </button>
  );
}

interface Row { label: string; value: unknown; unit: string; digits?: number; trust?: Trust | null; kind: "measured" | "twin" | "residual" }

function Schedule({ title, code, rows, children }: { title: string; code: string; rows: Row[]; children?: ReactNode }) {
  return (
    <section className="schedule" aria-label={title}>
      <header className="schedule-head">
        <h2>{title}</h2>
        <span className="code">{code}</span>
      </header>
      <table>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className={`k-${r.kind}`}>
              <th scope="row">{r.label}</th>
              <td className={`num${r.kind === "residual" && r.trust === "suspect" ? " struck" : ""}`}>{fmt(r.value, r.digits ?? 1)}</td>
              <td className="unit">{r.unit}{r.kind === "residual" && r.trust === "suspect" && <> <span className="trust-suspect">suspect</span></>}
                {r.kind === "twin" && r.trust === "estimated" && <span className="est"> est.</span>}</td>
              <td className="trust">{r.kind === "measured" && r.trust && r.trust !== "trusted" && <span className={`trust-${r.trust}`}>{r.trust === "estimated" ? "est." : r.trust}</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {children}
    </section>
  );
}

export function DataIn({ row, otiSuspect, meterOnly }: { row: Record<string, Cell> | null; otiSuspect: boolean; meterOnly: boolean }) {
  const r = row ?? {};
  const dq = (r["dq_flags"] as string) ?? "";
  const m = (label: string, key: string, unit: string, digits = 1): Row => ({
    label, value: r[key], unit, digits, kind: "measured", trust: row ? trustOf(key, r[key], dq, otiSuspect) : null,
  });
  void meterOnly;
  return (
    <Schedule title="Data in" code="Schedule 1" rows={[
      m("Top-oil, OTI", "OTI_C", "°C"), m("Hot-spot, WTI", "WTI_C", "°C"), m("Ambient, ATI", "ATI_C", "°C"),
      m("Current R", "IR", "A", 0), m("Current Y", "IY", "A", 0), m("Current B", "IB", "A", 0), m("Neutral", "IN", "A", 1),
      m("Voltage R", "VR", "V"), m("Voltage Y", "VY", "V"), m("Voltage B", "VB", "V"),
      m("Power factor", "PF", "", 3), m("Frequency", "freq_Hz", "Hz", 2), m("Oil level", "OLI_pct", "%"), m("Humidity", "RH_pct", "%", 0),
    ]} />
  );
}

export function TwinState({ row, otiSuspect }: { row: Record<string, Cell> | null; otiSuspect: boolean }) {
  const tw = (row ?? {}) as Record<string, unknown>;
  // measured − twin is only meaningful when the backend trusts the OTI reading it is built from
  const resTrust = row && trustOf("OTI_C", tw.OTI_C, String(tw.dq_flags ?? ""), otiSuspect) === "suspect" ? "suspect" as Trust : null;
  const t = (label: string, key: string, unit: string, digits = 1, kind: Row["kind"] = "twin"): Row =>
    ({ label, value: tw[key], unit, digits, kind });
  const est = (label: string, key: string, unit: string, digits = 1): Row => ({ ...t(label, key, unit, digits), trust: "estimated" });
  const SUBS = ["thermal", "ageing", "loading", "electrical", "integrity", "fault_stress"];
  const h = row && typeof tw.health_score === "number" ? {
    score: tw.health_score as number, band: String(tw.health_band),
    components: Object.fromEntries(SUBS.filter((k) => typeof tw[`health_${k}`] === "number").map((k) => [k, tw[`health_${k}`] as number])),
  } : null;
  return (
    <Schedule title="Twin state" code="Schedule 2" rows={[
      t("Load factor K", "load_pu", "pu", 2), est("Losses", "losses_total_W", "W", 0), est("Heat to air", "heat_dissipated_W", "W", 0),
      est("Bottom oil", "bottom_oil_C", "°C"), t("Top-oil", "twin_oil_C", "°C"), t("Hot-spot", "twin_hs_C", "°C"),
      { ...t("Measured − twin", "residual_oil_C", "K", 1, "residual"), trust: resTrust }, t("Ageing, expected", "aging_rate", "× normal", 2),
      t("Ageing, actual", "aging_rate_actual", "× normal", 2), t("Life used, actual", "days_aged_actual_cum", "days", 2),
      t("Fidelity, 24 h RMS", "fidelity_rmse_C", "K", 2),
    ]}>
      <div className="health">
        <div className="health-head">
          <h3>Health index</h3>
          {h && <span className={`stamp stamp-${h.band}`}>{h.band}</span>}
          <span className="num big">{fmt(h?.score, 0)}</span>
        </div>
        <table className="subscores">
          <tbody>
            {Object.entries(h?.components ?? {}).map(([k, v]) => (
              <tr key={k}><th scope="row">{k.replace("_", " ")}</th><td className="num">{fmt(v, 0)}</td>
                <td className="bar"><span style={{ width: `${Math.max(0, Math.min(100, v as number))}%` }} /></td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </Schedule>
  );
}

export function TitleBlock({ run, time, simulated }: { run: Run | undefined; time: string | null; simulated: boolean }) {
  const a = (run?.asset ?? {}) as Record<string, unknown>;
  const kv = (v: unknown, d: number) => (typeof v === "number" ? fmt(v / 1000, d) : null);
  const volts = [kv(a.hv_voltage_V, 0), kv(a.lv_voltage_V, 3)].filter(Boolean).join(" / ");
  const estimated = a.nameplate_source === "estimated";
  const rating = a.rating_kVA
    ? `${fmt(a.rating_kVA, 0)} kVA${volts ? `, ${volts} kV` : ""}${a.cooling ? `, ${a.cooling}` : ""}${estimated ? " (estimated from data)" : ""}`
    : "—";
  return (
    <div className="titleblock" role="contentinfo">
      {simulated && <div className="simstamp" aria-label="Simulated data">Simulated</div>}
      <table>
        <tbody>
          <tr><th>Drawing</th><td colSpan={3} className="title">Transformer-1 digital twin</td></tr>
          <tr><th>Asset</th><td colSpan={3}>{a.asset_id ? "Transformer-1, MAHE Bengaluru" : estimated ? "Unrated unit, rating estimated from data" : "—"}</td></tr>
          <tr><th>Rating</th><td colSpan={3}>{rating}</td></tr>
          <tr><th>Dataset</th><td colSpan={3}>{run?.name ?? "—"}</td></tr>
          <tr><th>Mode</th><td>{run?.mode ?? "—"}</td><th>Time</th><td>{time ? time.replace("T", " ").slice(0, 16) : "—"}</td></tr>
          <tr><th>Scale</th><td>Schematic, not to scale</td><th>Sheet</th><td>1 of 1</td></tr>
        </tbody>
      </table>
    </div>
  );
}
