// A small chat dock: ask about Transformer-1. The server answers from the live data and refuses anything else (server/chat.py).
import { useEffect, useRef, useState } from "react";

interface Msg { role: "user" | "assistant"; content: string; off?: boolean }

const IDEAS = ["Is the transformer healthy right now?", "Why is the hot spot where it is?", "What should I check if the earth current rises?", "What do the silica gel colours mean?"];

export function ChatDock({ dataset, hidden = false }: { dataset: string; hidden?: boolean }) {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs, busy, open]);

  const ask = async (q: string) => {
    const question = q.trim();
    if (!question || busy) return;
    const next: Msg[] = [...msgs, { role: "user", content: question }];
    setMsgs(next); setText(""); setBusy(true);
    try {
      const r = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dataset, messages: next.slice(-8).map(({ role, content }) => ({ role, content })) }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail ?? r.statusText);
      setMsgs([...next, { role: "assistant", content: j.answer, off: j.on_topic === false }]);
    } catch (e) {
      setMsgs([...next, { role: "assistant", content: `Could not answer: ${(e as Error).message}`, off: true }]);
    } finally { setBusy(false); }
  };

  if (hidden) return null;
  return (
    <>
      <button className="chat-fab" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Close" : "Ask the twin"}</button>
      {open && (
        <section className="chat-panel" role="dialog" aria-label="Ask about Transformer-1">
          <header><b>Ask about Transformer-1</b><span>Simulated data · answers only about this transformer</span></header>
          <div className="chat-log">
            {!msgs.length && (
              <div className="chat-ideas">
                <p>Ask about its readings, alerts, limits or maintenance.</p>
                {IDEAS.map((i) => <button key={i} onClick={() => ask(i)}>{i}</button>)}
              </div>
            )}
            {msgs.map((m, n) => <p key={n} className={`chat-msg ${m.role}${m.off ? " off" : ""}`}>{m.content}</p>)}
            {busy && <p className="chat-msg assistant wait">Thinking…</p>}
            <div ref={end} />
          </div>
          <form onSubmit={(e) => { e.preventDefault(); ask(text); }}>
            <input value={text} maxLength={600} placeholder="Ask about the transformer…" onChange={(e) => setText(e.target.value)} aria-label="Your question" />
            <button disabled={busy || !text.trim()}>Send</button>
          </form>
        </section>
      )}
    </>
  );
}
