// TABLET view (?view=tablet): the 3D twin, a live plant you can inject anomalies into, and the alerts the twin raises.
// Everything is SIMULATED. The plant takes the fault; the twin and the analytics only see the measurements
// (backend: sim/live.py, GET /api/live/stream). Frames are appended to the same player the other views read.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Scene } from "../twin/Scene";
import { HeatScale } from "../twin/HeatScale";
import { ThermalDiagram } from "../sheet/ThermalDiagram";
import { HeatBalance } from "../sheet/HeatBalance";
import { LifeClock } from "../twin/LifeClock";
import { ALL_ON, type Layers } from "../twin/layers";
import type { PartId } from "../twin/parts";
import { player, usePlayerIndex, type Cell } from "../player/player";
import "./tablet.css";

interface Param { key: string; label: string; min: number; max: number; step: number; default: number; unit: string }
interface Kind {
  kind: string; label: string; group: string; oneshot: boolean; desc: string; params: Param[];
  channel?: boolean; channels?: Record<string, string>;
}
interface Alert {
  id: string; timestamp: string; type: string; severity: "info" | "warning" | "critical"; origin: string;
  value: number | null; threshold: number | null; explanation: string;
}
interface Injection { id: number; kind: string; label: string; params: Record<string, number | string>; since_h: number }
interface Tick {
  tick: number; frame: Record<string, Cell>; alerts: Alert[]; injections: Injection[];
  events: { timestamp: string; peak_pu?: number; duration_ms?: number; phase?: string }[];
}
interface Info { i_rated_A: number; params: { P0_W: number; Pk_W: number }; asset: Record<string, unknown>; control: { rate: number; paused: boolean } }
interface Response { title: string; push: string; meaning: string; do_now: string[]; who: string }
interface Logged { alert: Alert; at: string }

const GROUPS = ["Load", "Thermal", "Electrical", "Oil", "Sensor"];
const SPEEDS: { label: string; rate: number }[] = [{ label: "Slow", rate: 1 }, { label: "Normal", rate: 2 }, { label: "Fast", rate: 5 }, { label: "Turbo", rate: 10 }];
const LAYERS: Layers = { ...ALL_ON, electrical: true, lag: false };

const post = (path: string, body?: unknown) =>
  fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) })
    .then(async (r) => { if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `${r.status}`); return r.json(); });
const simTime = (iso: string | undefined | null) => (iso ? iso.slice(5, 16).replace("T", " ") : "");
const num = (v: Cell | undefined) => (typeof v === "number" ? v : null);

export default function Tablet() {
  const [kinds, setKinds] = useState<Kind[]>([]);
  const [info, setInfo] = useState<Info | null>(null);
  const [responses, setResponses] = useState<Record<string, Response>>({});
  const [tick, setTick] = useState<Tick | null>(null);
  const [log, setLog] = useState<Logged[]>([]);
  const [status, setStatus] = useState<"connecting" | "live" | "paused" | "error">("connecting");
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<Kind | null>(null);
  const [vals, setVals] = useState<Record<string, number>>({});
  const [channel, setChannel] = useState("OTI_C");
  const [cut, setCut] = useState(false);
  const [details, setDetails] = useState(false);   // the thermometer and heat-balance overlays crowd the model, so they are optional
  const [pinned, setPinned] = useState<PartId[]>([]);
  const [rate, setRate] = useState(2);
  const [paused, setPaused] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const seen = useRef(new Set<string>());
  const abort = useRef<AbortController | null>(null);
  const alive = useRef(true);

  const onTick = useCallback((t: Tick) => {
    const { timestamp, ...rest } = t.frame as Record<string, Cell>;
    player.append(String(timestamp), rest);
    setTick(t);
    const fresh = t.alerts.filter((a) => !seen.current.has(a.id));
    if (fresh.length) {
      fresh.forEach((a) => seen.current.add(a.id));
      setLog((l) => [...fresh.map((alert) => ({ alert, at: String(timestamp) })).reverse(), ...l].slice(0, 60));
    }
  }, []);

  const connect = useCallback(async () => {
    abort.current?.abort();
    const ac = new AbortController();
    abort.current = ac;
    setStatus("connecting");
    try {
      const res = await fetch("/api/live/stream", { signal: ac.signal });
      if (!res.ok) throw new Error(`${res.status}`);
      setStatus("live");
      setError(null);
      const rd = res.body!.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await rd.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i: number;
        while ((i = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, i).trim();
          buf = buf.slice(i + 1);
          if (line) onTick(JSON.parse(line) as Tick);
        }
      }
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      setStatus("error");
      setError(`Cannot reach the backend (${(e as Error).message}). Retrying…`);
    }
    if (alive.current && !ac.signal.aborted) setTimeout(() => alive.current && connect(), 2000);
  }, [onTick]);

  useEffect(() => {
    alive.current = true;
    (async () => {
      try {
        const [cat, inf, resp] = await Promise.all([
          fetch("/api/live/catalogue").then((r) => r.json()),
          fetch("/api/live/info").then((r) => r.json()),
          fetch("/api/companion/responses").then((r) => (r.ok ? r.json() : { types: {} })),
        ]);
        setKinds(cat.injections);
        setInfo(inf);
        setRate(inf.control.rate);
        setPaused(inf.control.paused);
        setResponses(resp.types ?? {});
        connect();
      } catch (e) {
        setStatus("error");
        setError(`Cannot reach the backend (${(e as Error).message}).`);
      }
    })();
    return () => { alive.current = false; abort.current?.abort(); player.clear(); };
  }, [connect]);

  const i = usePlayerIndex();
  const row = useMemo(() => (i >= 0 ? player.row(i) : null), [i, player.rev]); // eslint-disable-line react-hooks/exhaustive-deps
  const live = i >= 0;

  const choose = (k: Kind) => {
    setSel(k);
    setVals(Object.fromEntries(k.params.map((p) => [p.key, p.default])));
    if (k.channels) setChannel(Object.keys(k.channels)[0]);
  };
  const run = async (fn: () => Promise<unknown>) => { try { setError(null); await fn(); } catch (e) { setError((e as Error).message); } };
  const inject = () => sel && run(async () => {
    await post("/api/live/inject", { kind: sel.kind, params: vals, channel: sel.channel ? channel : undefined });
    setSel(null);
  });
  const clearOne = (id: number) => run(() => post("/api/live/clear", { id }));
  const clearAll = () => run(() => post("/api/live/clear", {}));
  const refill = () => run(() => post("/api/live/refill"));
  const control = (body: { rate?: number; paused?: boolean }) => run(async () => {
    const c = await post("/api/live/control", body);
    setRate(c.rate);
    setPaused(c.paused);
  });
  const restart = () => run(async () => {
    abort.current?.abort();
    seen.current.clear();
    setLog([]);
    setTick(null);
    setSel(null);
    player.clear();
    await post("/api/live/session", { seed: Math.floor(Math.random() * 1000) });
    await post("/api/live/control", { paused: false });
    setPaused(false);
    connect();
  });

  const calloutData = useMemo(() => ({
    row: row as Record<string, unknown> | null, twin: row as Record<string, unknown> | null,
    asset: info?.asset ?? null, otiSuspect: false, error,
  }), [row, info, error]);
  const ratedW = info ? info.params.P0_W + info.params.Pk_W : null;
  const oil = num(row?.OLI_pct);
  const band = String(row?.health_band ?? "");
  const score = num(row?.health_score);
  const res = num(row?.residual_oil_C);

  return (
    <div className="tw">
      <header className="tw-top">
        <b className="tw-title">Transformer-1 · live simulation</b>
        <span className="tw-sim" title="Everything on this screen is generated, not measured on a real transformer">SIMULATED</span>
        <span className="tw-clock">{simTime(row ? String(player.frames?.iso[i] ?? "") : null)}</span>
        {score !== null && <span className={`tw-health ${band}`}>Health {Math.round(score)} · {band}</span>}
        <span className="tw-spacer" />
        <div className="tw-seg" role="group" aria-label="Speed">
          {SPEEDS.map((s) => <button key={s.label} aria-pressed={rate === s.rate} onClick={() => control({ rate: s.rate })}>{s.label}</button>)}
        </div>
        <button onClick={() => control({ paused: !paused })}>{paused ? "Resume" : "Pause"}</button>
        <button onClick={() => setCut(!cut)} aria-pressed={cut}>Cut-away</button>
        <button onClick={() => setDetails(!details)} aria-pressed={details}>Details</button>
        <button onClick={restart}>Restart</button>
        <span className={`tw-status ${status}`}>{status === "live" ? (paused ? "paused" : "live") : status}</span>
      </header>

      <aside className="tw-left">
        <h2>Inject an anomaly</h2>
        <p className="tw-note">The plant takes the fault. The twin does not know, and has to spot it from the measurements.</p>
        {GROUPS.map((g) => (
          <section key={g}>
            <h3>{g}</h3>
            <div className="tw-chips">
              {kinds.filter((k) => k.group === g).map((k) => (
                <button key={k.kind} className="tw-chip" aria-pressed={sel?.kind === k.kind} onClick={() => choose(k)}>{k.label}</button>
              ))}
            </div>
          </section>
        ))}
        {sel && (
          <div className="tw-form">
            <b>{sel.label}</b>
            <p>{sel.desc}</p>
            {sel.channel && sel.channels && (
              <label>Sensor
                <select value={channel} onChange={(e) => setChannel(e.target.value)}>
                  {Object.entries(sel.channels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </label>
            )}
            {sel.params.map((p) => (
              <label key={p.key}>{p.label}: <b>{vals[p.key]} {p.unit}</b>
                <input type="range" min={p.min} max={p.max} step={p.step} value={vals[p.key] ?? p.default}
                  onChange={(e) => setVals({ ...vals, [p.key]: Number(e.target.value) })} />
              </label>
            ))}
            <div className="tw-row">
              <button className="primary" onClick={inject}>{sel.oneshot ? "Fire" : "Inject"}</button>
              <button onClick={() => setSel(null)}>Cancel</button>
            </div>
          </div>
        )}
      </aside>

      <section className="field tw-field" aria-label="Transformer-1, three-dimensional schematic">
        <Scene cut={cut} pinned={pinned} setPinned={setPinned} data={calloutData} oilLevelPct={oil} thermal={live}
          layers={LAYERS} ratedW={ratedW} iRated={info?.i_rated_A ?? null} events={tick?.events ?? []} />
        {live && details && <ThermalDiagram meterOnly={false} otiSuspect={false} />}
        {live && details && <HeatBalance />}
        {live && <HeatScale meterOnly={false} otiSuspect={false} />}
        {!live && <p className="field-note">{status === "error" ? (error ?? "Cannot reach the backend") : "Starting the plant…"}</p>}
        <p className="field-hint">Drag to turn. Tap a part to read it.</p>
      </section>

      <aside className="tw-right">
        <h2>Active anomalies</h2>
        {tick?.injections.length ? (
          <ul className="tw-active">
            {tick.injections.map((n) => (
              <li key={n.id}><span><b>{n.label}</b> <i>{n.since_h} h</i></span><button aria-label={`Clear ${n.label}`} onClick={() => clearOne(n.id)}>✕</button></li>
            ))}
          </ul>
        ) : <p className="tw-note">None. The transformer is running normally.</p>}
        <div className="tw-row">
          <button onClick={clearAll} disabled={!tick?.injections.length}>Clear all</button>
          <button onClick={refill} title="Undo an oil leak or theft">Refill oil</button>
        </div>
        <div className="tw-read">
          <span>Measured oil</span><b>{num(row?.OTI_C)?.toFixed(1) ?? "–"} °C</b>
          <span>Twin predicts</span><b>{num(row?.twin_oil_C)?.toFixed(1) ?? "–"} °C</b>
          <span>Gap</span><b className={res !== null && Math.abs(res) > 3 ? "bad" : ""}>{res === null ? "–" : `${res >= 0 ? "+" : "−"}${Math.abs(res).toFixed(1)} K`}</b>
          <span>Load</span><b>{num(row?.load_pu) !== null ? `${(num(row?.load_pu)! * 100).toFixed(0)} %` : "–"}</b>
          <span>Oil level</span><b>{oil !== null ? `${oil.toFixed(1)} %` : "–"}</b>
        </div>
        {live && <LifeClock meterOnly={false} />}
        <h2>Alerts</h2>
        {!log.length && <p className="tw-note">Nothing raised yet.</p>}
        <ul className="tw-alerts">
          {log.map(({ alert: a, at }) => {
            const r = responses[a.type];
            const isOpen = open === a.id;
            return (
              <li key={a.id} className={`sev-${a.severity}`}>
                <button className="tw-alert" onClick={() => setOpen(isOpen ? null : a.id)} aria-expanded={isOpen}>
                  <span className="tw-alert-top"><b>{r?.title ?? a.type}</b><i>{simTime(at)}</i></span>
                  <span>{r?.push ?? a.explanation}</span>
                </button>
                {isOpen && (
                  <div className="tw-alert-more">
                    {a.origin === "sensor" && <p><b>Check the sensor, not the transformer.</b></p>}
                    {r && <p>{r.meaning}</p>}
                    {r && <ol>{r.do_now.map((s) => <li key={s}>{s}</li>)}</ol>}
                    <p className="tw-detail">{a.type}{a.value !== null ? ` · value ${+a.value.toPrecision(4)}` : ""}{a.threshold !== null ? ` · threshold ${+a.threshold.toPrecision(4)}` : ""}<br />{a.explanation}</p>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </aside>

      {error && live && <p className="tw-error" role="alert">{error}</p>}
    </div>
  );
}
