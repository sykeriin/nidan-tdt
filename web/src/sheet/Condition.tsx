// CONDITION: the engineer's checklist as one live board. Every quantity with its value, its limit and a status, computed by the
// backend (twin/condition.py) against the India profile (IS 2026, IS 1180, IS 6600, IS 1866, CEA). Live transformer only.
import { useQuery } from "@tanstack/react-query";

export interface CondItem {
  id: string; group: string; title: string; value: number | null; unit: string; limit: string;
  status: "ok" | "watch" | "alarm" | "na"; detail: string; standard: string; colour?: string;
}
interface Board { timestamp: string; standard: string; items: CondItem[]; silica_scale: { upto: number; colour: string; label: string }[] }

export const useCondition = (enabled: boolean) =>
  useQuery({
    queryKey: ["condition"], enabled, refetchInterval: 3000, retry: true, retryDelay: 2000,
    queryFn: async () => {
      const r = await fetch("/api/live/condition");
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText);
      return (await r.json()) as Board;
    },
  });

const STATUS = { ok: "Within limits", watch: "Watch", alarm: "Alarm", na: "No reading" } as const;
const fmt = (v: number | null) => (v == null || Number.isNaN(v) ? "—" : Math.abs(v) >= 1000 ? v.toFixed(0) : Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2));
const GROUPS = ["Faults", "Loading", "Thermal", "Electrical", "Insulation", "Life", "Oil", "Efficiency"];

const post = (path: string, body: unknown) => fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function Bar({ v, lo, hi, marks }: { v: number; lo: number; hi: number; marks: number[] }) {
  const at = (x: number) => `${Math.min(100, Math.max(0, ((x - lo) / (hi - lo)) * 100))}%`;
  return (
    <div className="cd-bar" aria-hidden>
      {marks.map((m) => <i key={m} style={{ left: at(m) }} />)}
      <b style={{ left: at(v) }} />
    </div>
  );
}

function Card({ it, scale }: { it: CondItem; scale: Board["silica_scale"] }) {
  return (
    <div className={`ck-card cd-card ${it.status}`}>
      <h3>{it.title}<em className={`cd-chip ${it.status}`}>{STATUS[it.status]}</em></h3>
      <div className="cd-val"><b>{fmt(it.value)}</b><span>{it.unit}</span></div>
      {it.id === "silica_gel" && (
        <div className="cd-gel">
          <span className="cd-jar" style={{ background: it.colour }} title={it.detail} />
          <div className="cd-scale">{scale.map((s) => <i key={s.upto} style={{ background: s.colour }} title={s.label} />)}</div>
        </div>
      )}
      {it.id === "moisture" && it.value != null && <Bar v={it.value} lo={0} hi={40} marks={[20, 30]} />}
      {it.id === "voltage" && it.value != null && <Bar v={it.value} lo={-10} hi={10} marks={[-6, 6]} />}
      <p className="cd-limit">Limit: {it.limit}</p>
      <p className="cd-detail">{it.detail}</p>
      {it.standard && <p className="cd-std">{it.standard}</p>}
    </div>
  );
}

export function Condition({ onClose }: { onClose: () => void }) {
  const q = useCondition(true);
  const d = q.data;
  const svc = (action: string) => post("/api/live/service", { action }).then(() => q.refetch());
  const counts = d ? { alarm: d.items.filter((i) => i.status === "alarm").length, watch: d.items.filter((i) => i.status === "watch").length } : null;
  return (
    <div className="circuit condition" role="dialog" aria-label="Condition board">
      <div className="ck-head">
        <h2>Condition board<span>{d ? `${d.standard} · ${new Date(d.timestamp).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}` : "live transformer"}</span></h2>
        <div className="cd-actions">
          {counts && <span className={`cd-summary ${counts.alarm ? "alarm" : counts.watch ? "watch" : "ok"}`}>
            {counts.alarm ? `${counts.alarm} alarm${counts.alarm > 1 ? "s" : ""}` : counts.watch ? `${counts.watch} to watch` : "All within limits"}</span>}
          <button onClick={() => svc("dry_oil")} title="Service action: dry the oil and put fresh silica gel in the breather">Dry oil, new gel</button>
          <button onClick={() => svc("refill")} title="Service action: refill the oil">Refill oil</button>
          <button onClick={onClose}>Close</button>
        </div>
      </div>
      {q.isLoading && <p className="ml-wait">Reading the live transformer…</p>}
      {q.error && <p className="ml-wait">{(q.error as Error).message}. Choose “Live transformer” as the source and wait a moment.</p>}
      {d && GROUPS.map((g) => {
        const items = d.items.filter((i) => i.group === g);
        return items.length ? (
          <section key={g} className="cd-group">
            <h4>{g}</h4>
            <div className="cd-grid">{items.map((it) => <Card key={it.id} it={it} scale={d.silica_scale} />)}</div>
          </section>
        ) : null;
      })}
      {d && <p className="cd-foot">Limits marked as practice or assumed in <code>config/thresholds.yaml</code> are common utility settings, not clauses: confirm them with your utility. Silica gel colour follows a cobalt-chloride indicator (blue dry, pink saturated).</p>}
    </div>
  );
}
