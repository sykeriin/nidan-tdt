// Anomaly tests: every alert type the backend can raise, with the companion app's pre-written response, and a button
// that sends a TEST notification (browser notification plus an on-page banner) exactly as the companion app would.
// The text comes from GET /api/companion/responses (companion/content/responses.json).
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

type Sev = "info" | "warning" | "critical";
interface Resp {
  title: string; push: string; meaning: string; safe_to_wait: string; do_now: string[]; check: string[]; escalate_if: string; who: string;
  urgency: Record<Sev, string>;
}
interface Content {
  severity_label: Record<Sev, string>; urgency_label: Record<string, string>; types: Record<string, Resp>;
}

const useContent = () =>
  useQuery({
    queryKey: ["companion-responses"], staleTime: Infinity, retry: false,
    queryFn: async () => {
      const r = await fetch("/api/companion/responses");
      if (!r.ok) throw new Error("The companion responses could not be loaded from the server.");
      return (await r.json()) as Content;
    },
  });

export function AnomalyTests() {
  const q = useContent();
  const [sev, setSev] = useState<Sev>("warning");
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => { if (!notice) return; const h = setTimeout(() => setNotice(null), 7000); return () => clearTimeout(h); }, [notice]);

  const rows = useMemo(() => {
    const t = q.data?.types ?? {};
    const f = filter.trim().toLowerCase();
    return Object.entries(t).filter(([id, r]) => !f || id.includes(f) || r.title.toLowerCase().includes(f) || r.who.toLowerCase().includes(f));
  }, [q.data, filter]);

  // The test goes to the server's queue; the companion apps (phone app, companion web app) poll it and show the notification.
  const send = async (id: string, r: Resp) => {
    const label = q.data?.severity_label[sev] ?? sev;
    const title = `TEST: ${label}: ${r.title}`;
    try {
      const res = await fetch("/api/companion/test-alert", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ type: id, severity: sev }) });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `The server answered ${res.status}.`);
      setNotice(`Sent to the companion apps: ${title}. It arrives within a few seconds on any phone that is monitoring.`);
    } catch (e) {
      setNotice(`Could not send the test: ${(e as Error).message}`);
    }
  };

  if (q.isError) return <p className="wb-note err" role="alert">{(q.error as Error).message}</p>;
  if (!q.data) return <p className="wb-note">Loading the alert library…</p>;
  return (
    <div className="at">
      {notice && <div className={`at-banner sev-${sev}`} role="status">{notice}</div>}
      <p className="wb-note">
        Each of the {Object.keys(q.data.types).length} alert types the analytics can raise, with the response the companion app gives the technician.
        Send test queues a TEST alert on the server, and every companion app that is open or monitoring shows it as a notification, marked TEST. Nothing is raised on the transformer.
      </p>
      <div className="wb-row">
        <label className="at-sev">Severity{" "}
          <select value={sev} onChange={(e) => setSev(e.target.value as Sev)} aria-label="Severity of the test">
            {(["info", "warning", "critical"] as Sev[]).map((s) => <option key={s} value={s}>{q.data.severity_label[s]}</option>)}
          </select>
        </label>
        <input type="text" placeholder="Filter by name or who handles it" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter alert types" />
        <a className="wb-btn" href="/companion/" target="_blank" rel="noreferrer">Open the companion app</a>
      </div>
      <ul className="at-list">
        {rows.map(([id, r]) => (
          <li key={id} className="at-card">
            <div className="at-head">
              <div><h4>{r.title}</h4><small>{id} · {r.who} · {q.data!.urgency_label[r.urgency[sev]] ?? ""}</small></div>
              <div className="wb-row">
                <button className="wb-btn" onClick={() => setOpen(open === id ? null : id)} aria-expanded={open === id}>{open === id ? "Hide" : "Response"}</button>
                <button className="wb-btn on" onClick={() => send(id, r)}>Send test</button>
              </div>
            </div>
            <p className="at-push">{r.push}</p>
            {open === id && (
              <div className="at-body">
                <p><b>What it means.</b> {r.meaning}</p>
                <p><b>Can it wait?</b> {r.safe_to_wait}</p>
                <div className="wb-cols">
                  <div><b>Do now</b><ol>{r.do_now.map((s) => <li key={s}>{s}</li>)}</ol></div>
                  <div><b>Check</b><ul>{r.check.map((s) => <li key={s}>{s}</li>)}</ul></div>
                </div>
                <p><b>Escalate if.</b> {r.escalate_if}</p>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
