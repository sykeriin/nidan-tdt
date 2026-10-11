// CONDITION: the engineer's checklist as one live board. Every quantity with its value, where it sits between its limits, and a
// status, computed by the backend (twin/condition.py) against the India profile (IS 2026, IS 1180, IS 6600, IS 1866, CEA).
import { useQuery } from "@tanstack/react-query";

interface Scale { min: number; max: number; watch: number | null; alarm: number | null; dir: "high" | "low" | "band"; ref?: number }
export interface CondItem {
  id: string; group: string; title: string; value: number | null; unit: string; limit: string;
  status: "ok" | "watch" | "alarm" | "na"; detail: string; standard: string; colour?: string; scale: Scale | null;
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
const fmt = (v: number | null) => (v == null || Number.isNaN(v) ? "—" : Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2));
const GROUPS: [string, string][] = [["Faults", "Faults and protection"], ["Loading", "Loading"], ["Thermal", "Temperatures and cooling"], ["Electrical", "Electrical"],
  ["Insulation", "Insulation"], ["Life", "Life"], ["Oil", "Oil and breather"], ["Efficiency", "Efficiency"]];
const OK = "#3B7A3E", WARN = "#E0A526", BAD = "#B42318";

const post = (path: string, body: unknown) => fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

/** A track coloured green, amber and red by the item's own limits, with a marker where the value sits. */
function Gauge({ s, v }: { s: Scale; v: number }) {
  const span = s.max - s.min || 1;
  const at = (x: number) => Math.min(100, Math.max(0, ((x - s.min) / span) * 100));
  const w = s.watch ?? s.alarm ?? s.max, a = s.alarm ?? s.max;
  let stops: string;
  if (s.dir === "high") stops = `${OK} 0 ${at(w)}%, ${WARN} ${at(w)}% ${at(a)}%, ${BAD} ${at(a)}% 100%`;
  else if (s.dir === "low") stops = `${BAD} 0 ${at(a)}%, ${WARN} ${at(a)}% ${at(w)}%, ${OK} ${at(w)}% 100%`;
  else stops = `${BAD} 0 ${at(-a)}%, ${WARN} ${at(-a)}% ${at(-w)}%, ${OK} ${at(-w)}% ${at(w)}%, ${WARN} ${at(w)}% ${at(a)}%, ${BAD} ${at(a)}% 100%`;
  return (
    <div className="cd-gauge" aria-hidden>
      <div className="cd-track" style={{ background: `linear-gradient(90deg, ${stops})` }}>
        {s.ref != null && <i className="cd-ref" style={{ left: `${at(s.ref)}%` }} />}
        <b className="cd-mark" style={{ left: `${at(v)}%` }} />
      </div>
      <div className="cd-ends"><span>{fmt(s.min)}</span><span>{fmt(s.max)}</span></div>
    </div>
  );
}

function Card({ it, scale }: { it: CondItem; scale: Board["silica_scale"] }) {
  return (
    <article className={`cd-card ${it.status}`}>
      <header><h3>{it.title}</h3><em className={`cd-chip ${it.status}`}>{STATUS[it.status]}</em></header>
      <div className="cd-val"><b>{fmt(it.value)}</b><span>{it.unit}</span></div>
      {it.scale && it.value != null && <Gauge s={it.scale} v={it.value} />}
      {it.id === "silica_gel" && (
        <div className="cd-gel">
          <span className="cd-jar" style={{ background: it.colour }} title={it.detail} />
          <div className="cd-scale">{scale.map((s) => <i key={s.upto} style={{ background: s.colour }} title={s.label} />)}</div>
        </div>
      )}
      <p className="cd-limit">{it.limit}</p>
      <p className="cd-detail">{it.detail}</p>
      {it.standard && <p className="cd-std">{it.standard}</p>}
    </article>
  );
}

export function Condition({ onClose }: { onClose: () => void }) {
  const q = useCondition(true);
  const d = q.data;
  const svc = (action: string) => post("/api/live/service", { action }).then(() => q.refetch());
  const n = (s: string) => d?.items.filter((i) => i.status === s).length ?? 0;
  const alarms = n("alarm"), watch = n("watch");
  const worst = d?.items.filter((i) => i.status === "alarm").map((i) => i.title).slice(0, 3).join(", ");
  return (
    <div className="circuit condition" role="dialog" aria-label="Condition board">
      <div className="ck-head">
        <h2>Condition board<span>{d ? `${d.standard} · ${new Date(d.timestamp).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}` : "live transformer"}</span></h2>
        <div className="cd-actions">
          <button onClick={() => svc("dry_oil")} title="Service action: dry the oil and put fresh silica gel in the breather">Dry oil, new gel</button>
          <button onClick={() => svc("refill")} title="Service action: refill the oil">Refill oil</button>
          <button onClick={onClose}>Close</button>
        </div>
      </div>
      {q.isLoading && <p className="ml-wait">Reading the transformer…</p>}
      {q.error && <p className="ml-wait">{(q.error as Error).message}. Choose “Live transformer” as the source and wait a moment.</p>}
      {d && (
        <>
          <section className={`cd-banner ${alarms ? "alarm" : watch ? "watch" : "ok"}`}>
            <div className="cd-tiles">
              <div className="alarm"><b>{alarms}</b><span>in alarm</span></div>
              <div className="watch"><b>{watch}</b><span>to watch</span></div>
              <div className="ok"><b>{n("ok")}</b><span>within limits</span></div>
            </div>
            <p>{alarms ? `Needs attention: ${worst}${alarms > 3 ? " and more" : ""}.` : watch ? "Nothing in alarm. A few readings are close to their limits." : "Everything is inside its limits."}</p>
          </section>
          {GROUPS.map(([g, label]) => {
            const items = d.items.filter((i) => i.group === g);
            return items.length ? (
              <section key={g} className="cd-group">
                <h4>{label}<span>{items.length}</span></h4>
                <div className="cd-grid">{items.map((it) => <Card key={it.id} it={it} scale={d.silica_scale} />)}</div>
              </section>
            ) : null;
          })}
          <p className="cd-foot">Limits marked as practice or assumed in <code>config/thresholds.yaml</code> are common utility settings, not clauses: confirm them with your utility. Silica gel colour follows a cobalt-chloride indicator (blue dry, pink saturated).</p>
        </>
      )}
    </div>
  );
}
