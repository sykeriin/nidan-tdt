import { useEffect, useMemo, useRef, useState } from "react";
import { Scene } from "./twin/Scene";
import { PART, type PartId } from "./twin/parts";
import { HeatScale } from "./twin/HeatScale";
import { DataIn, Frame, SectionToggle, SheetTabs, TitleBlock, TwinState, type TwinMode } from "./sheet/Sheet";
import { Timeline } from "./sheet/Timeline";
import { useDatasets, useFindings, useFramesQuery, useLiveSync, downloadReport, LIVE, useRunSummary, useComponents, useThermalParams, useWhatIf, useWhatIfDay, type Alert, type WhatIfInput } from "./api/client";
import { DiagnosePanel, findingMarks } from "./sheet/Diagnose";
import { TourCaption, tour, useTourStep } from "./twin/Tour";
import { SimCalc, SimPhysics, SimPresets } from "./sheet/SimPhysics";
import { Circuit } from "./sheet/Circuit";
import Tablet from "./tablet/Tablet";
import { Condition } from "./sheet/Condition";
import { ChatDock } from "./chat/Chat";
import "./tablet/tablet.css";
import { DiagnoseML } from "./sheet/DiagnoseML";
import { SimControls, SimInputs, useSettled, whatIfDayFrames, whatIfFrames } from "./sheet/Simulate";
import { ThermalDiagram } from "./sheet/ThermalDiagram";
import { LagTraces } from "./sheet/LagTraces";
import { LayerList } from "./sheet/LayerList";
import { Detail, detailLetter } from "./sheet/Detail";
import { HeatBalance } from "./sheet/HeatBalance";
import { ImportData } from "./sheet/ImportData";
import { PowerFlowReadout } from "./twin/PowerFlow";
import { StageLeft, StageRight, StageTrends, ViewModes, type ViewMode } from "./stage/Stage";
import { Workbench } from "./workbench/Workbench";
import "./workbench/workbench.css";
import { V2Layers, V2Left, V2Right } from "./v2/V2";
import "./v2/v2.css";
import "./workbench/compact.css";
import "./stage/stage.css";
import { LifeClock } from "./twin/LifeClock";
import { ALL_ON, type Layers } from "./twin/layers";
import { player, usePlayerIndex, type Cell, type Frames } from "./player/player";

// URL parameters make any view reproducible: ?ds=S2&t=2026-04-25T12:00&pin=winding-Y,oti&cut=0&play=1&mode=simulate
const q = new URLSearchParams(window.location.search);
const V2 = q.get("ui") === "clean"; // ?ui=clean: the simplified light layout (the drawing sheet is the default)
const DETAIL_W = 330; // px, must match .detail width in index.css
const INITIAL_PINS = (q.get("pin") ?? "").split(",").filter((p): p is PartId => p in PART);

export default function App() {
  const [dataset, setDataset] = useState(q.get("ds") ?? LIVE);   // the simulated live transformer is the default source; the replay datasets are chosen explicitly
  const [cut, setCut] = useState(q.get("cut") === "1");
  const [mode, setMode] = useState<TwinMode>("mirror");
  const [pinned, setPinned] = useState<PartId[]>(INITIAL_PINS);
  const [layers, setLayers] = useState<Layers>(V2 ? { ...ALL_ON, thermometer: false, lag: false, lifeclock: false } : ALL_ON);
  const [bench, setBench] = useState(false);
  const [xray, setXray] = useState(false);
  const [circuit, setCircuit] = useState(false);
  const [liveOn, setLiveOn] = useState(false);
  const [condOn, setCondOn] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);

  const [exporting, setExporting] = useState<string | null>(null);
  const [big, setBig] = useState(false); // expanded 3D view: the model box fills the window
  useEffect(() => { if (!big) return; const k = (e: KeyboardEvent) => e.key === "Escape" && setBig(false); window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [big]);
  const touring = useTourStep() >= 0;

  const datasets = useDatasets();
  const info = datasets.data?.find((d) => d.dataset_id === dataset);
  const isLive = dataset === LIVE;
  const sync = useLiveSync(isLive);
  const rev = isLive ? sync.data?.last_timestamp ?? "" : "";
  const liveReady = !isLive || sync.isSuccess;
  const run = useRunSummary(dataset, rev, liveReady);
  const snapshot = run.data?.mode === "snapshot";
  const framesQ = useFramesQuery(dataset, run.isSuccess && !snapshot && liveReady, rev);
  const meterOnly = run.data?.mode === "meter_only";
  const otiSuspect = (run.data?.summary as Record<string, any> | undefined)?.plausibility?.OTI_C === "suspect";

  const frames: Frames | null = useMemo(() => {
    const d = framesQ.data;
    if (!d) return null;
    return { dataset, iso: d.timestamp, t: d.timestamp.map((s) => Date.parse(s)), cols: d.columns as Frames["cols"] };
  }, [framesQ.data, dataset]);

  useEffect(() => {
    if (!frames) return;
    const t0 = q.get("t") && dataset === (q.get("ds") ?? LIVE) ? Date.parse(q.get("t")!) : undefined;
    if (dataset === LIVE) player.load(frames, frames.t[frames.t.length - 1]);   // the live transformer: always at the newest reading
    else player.load(frames, Number.isNaN(t0) ? undefined : t0);
    if (q.get("play") === "1") player.play();
    return () => player.pause();
  }, [frames, dataset]);

  // ---- SIMULATE: the what-if answer is loaded into the replay clock as a one-row frame
  const sim = mode === "simulate";
  const [simIn, setSimIn] = useState<WhatIfInput | null>(null);
  const [simFrom, setSimFrom] = useState<string | null>(null);
  const replayT = useRef<number | null>(null);
  const simHeld = useRef<Record<string, Cell>>({}); // the cursor's measured row when Simulate opened, then the last day's
  const dayFor = useRef(""); // the inputs whose what-if day is in the player
  const wq = useWhatIf(sim ? simIn : null, dataset, simFrom);
  const settled = useSettled(simIn);
  const dq = useWhatIfDay(sim ? settled : null, dataset, simFrom);
  // while a ruler moves: the instant steady answer as a one-row frame, so the 3D follows the hand
  useEffect(() => {
    if (sim && wq.data && !wq.isPlaceholderData && dayFor.current !== JSON.stringify(simIn))
      player.load(whatIfFrames(wq.data, dataset, simHeld.current));
  }, [sim, wq.data, wq.isPlaceholderData, dataset]); // eslint-disable-line react-hooks/exhaustive-deps
  // once the rulers rest: the what-if day (health, trends, power flow, alerts) replaces it
  useEffect(() => {
    if (!sim || !dq.data || dq.isPlaceholderData || JSON.stringify(settled) !== JSON.stringify(simIn)) return;
    player.load(whatIfDayFrames(dq.data, dataset), Date.parse(dq.data.cursor));
    dayFor.current = JSON.stringify(settled);
    simHeld.current = player.row();
  }, [sim, dq.data, dq.isPlaceholderData, dataset]); // eslint-disable-line react-hooks/exhaustive-deps
  const clamp = (v: unknown, lo: number, hi: number, dflt: number) =>
    typeof v === "number" ? Math.min(hi, Math.max(lo, v)) : dflt;
  const switchMode = (m: TwinMode) => {
    if (m === mode) return;
    if (m === "simulate") {
      const r = player.frames && !player.frames.dataset.endsWith("#sim") ? player.row() : {};
      simHeld.current = r;
      dayFor.current = "";
      replayT.current = player.t;
      setSimFrom(frames && player.index >= 0 ? frames.iso[player.index] : null);
      // start from what the transformer is doing at the cursor (cooling: the measured radiator effectiveness)
      setSimIn({ load: Math.round(clamp(r.load_pu, 0.3, 1.4, 0.75) * 100) / 100, ambient: Math.round(clamp(r.amb_C, 15, 50, 30) * 2) / 2,
        cooling: Math.round(clamp(r.radiator_effectiveness, 0.5, 1, 1) * 100) / 100,
        voltage: 1, pf: Math.round(clamp(r.PF, 0.7, 1, 0.95) * 100) / 100, unbalance: 0, profile: "steady" });
      setPinned([]);
    }
    if (m === "diagnose") setLayers((l) => ({ ...l, electrical: true }));
    if (mode === "simulate" && frames) player.load(frames, replayT.current ?? undefined);
    setMode(m);
  };
  const live = sim ? !!wq.data : !!frames; // the thermal layers have data to draw
  // ?mode=simulate|diagnose (&load=&amb=&cool= for Simulate): applied once, after the replay has loaded
  const urlMode = useRef(q.get("mode") as TwinMode | null);
  useEffect(() => {
    if (frames && q.get("tour") !== null && tour.step < 0) tour.go(Number(q.get("tour")) - 1); // ?tour=N: open at step N
    const m = urlMode.current;
    if (!frames || !m || m === "mirror") return;
    urlMode.current = null;
    switchMode(m);
    if (m === "simulate") {
      const n = (k: string) => (q.get(k) === null ? undefined : Number(q.get(k)));
      setSimIn((cur) => cur && { load: n("load") ?? cur.load, ambient: n("amb") ?? cur.ambient, cooling: n("cool") ?? cur.cooling,
        voltage: n("volt") ?? cur.voltage, pf: n("pf") ?? cur.pf, unbalance: n("unbal") ?? cur.unbalance,
        profile: q.get("profile") === "daily" ? "daily" : cur.profile });
    }
  }, [frames]); // eslint-disable-line react-hooks/exhaustive-deps

  const i = usePlayerIndex();
  const comp = useComponents(dataset, frames && i >= 0 && !sim ? frames.iso[i] : null, pinned.length > 0 && !V2 && !sim);
  const simDay = sim && (player.frames?.t.length ?? 0) > 1; // the what-if day (not the one-row steady frame) is loaded
  const simDayState = { data: dq.data, busy: dq.isFetching || JSON.stringify(settled) !== JSON.stringify(simIn),
    error: dq.error ? (dq.error as Error).message : null };
  const params = useThermalParams(dataset, frames?.iso[0] ?? null).data;
  const ratedW = params ? params.P0_W + params.Pk_W : null; // arrow-width scale only
  // ---- DIAGNOSE: findings up to the cursor, numbered on the parts they concern
  const diag = mode === "diagnose";
  const [focusPart, setFocusPart] = useState<PartId | null>(null);
  const [hl, setHl] = useState<PartId[] | null>(null);
  const fq = useFindings(dataset, frames && i >= 0 ? frames.iso[i] : null, diag && !!frames);
  const marks = useMemo(() => (diag ? findingMarks(fq.data) : {}), [diag, fq.data]);
  const panelOpen = diag || (!!pinned.length && !!frames && !sim);
  const bubbles = diag
    ? Object.fromEntries(Object.entries(marks).map(([p, m]) => [p, m!.nums.join(",")]))
    : V2 && frames && !sim ? Object.fromEntries(pinned.map((id) => [id, detailLetter(pinned, id)])) : undefined;
  const bubbleClass = diag ? Object.fromEntries(Object.entries(marks).map(([p, m]) => [p, `sev-${m!.sev}`])) : undefined;

  const row = useMemo(() => (frames && i >= 0 ? player.row(i) : null), [frames, i, player.rev]); // eslint-disable-line react-hooks/exhaustive-deps
  const error = (framesQ.error ?? run.error)?.message ?? null;

  const calloutData = useMemo(() => ({
    row: row as Record<string, unknown> | null,
    twin: row as Record<string, unknown> | null,
    asset: (run.data?.asset as Record<string, unknown>) ?? null,
    otiSuspect,
    error,
  }), [row, run.data, otiSuspect, error]);

  const alerts = (run.data?.analysis.alerts ?? []) as Alert[];
  const events = (run.data?.events.rows ?? []) as Record<string, unknown>[];
  const oil = row?.OLI_pct;

  // one page at a time: opening one closes the others, and so does choosing a sheet tab or another source
  const closeAll = () => { setCircuit(false); setCondOn(false); setBench(false); setLiveOn(false); setChatOpen(false); closeMenus(); };
  const openOnly = (k: "circuit" | "cond" | "bench" | "inject" | "chat") => {
    const was = { circuit, cond: condOn, bench, inject: liveOn, chat: chatOpen }[k];
    closeAll();
    if (!was) ({ circuit: setCircuit, cond: setCondOn, bench: setBench, inject: setLiveOn, chat: setChatOpen })[k](true);
  };
  const closeMenus = () => document.querySelectorAll("details.hdr-more[open], details.export-menu[open]").forEach((d) => d.removeAttribute("open"));
  const doReport = async () => {
    closeMenus();
    setExporting("report");
    try {
      const snap = (window as unknown as { __dtSnapshot?: () => string | null }).__dtSnapshot?.() ?? null;
      if (!snap) window.alert("The 3D picture could not be captured from this browser. The report will use a drawn picture of the transformer state instead.");
      await downloadReport(dataset, snap);
    } catch (e) { window.alert(`Could not make the report: ${(e as Error).message}`); }
    finally { setExporting(null); }
  };
  const tools = [
    { k: "tour", label: touring ? "Stop tour" : "Explain", hint: "60 s guided tour", pressed: touring, disabled: !frames, title: "",
      act: () => { if (touring) { tour.stop(); return; } closeAll(); switchMode("mirror"); setPinned([]); setCut(true); setLayers(ALL_ON); tour.start(); } },
    { k: "bench", label: "Workbench", hint: "Profile, physics", pressed: bench, disabled: false, title: "", act: () => openOnly("bench") },
    { k: "circuit", label: "Circuit", hint: "Electrical, live", pressed: circuit, disabled: !frames, title: "", act: () => openOnly("circuit") },
    { k: "inject", label: "Inject faults", hint: "Live transformer", pressed: liveOn, disabled: false, title: "", act: () => openOnly("inject") },
    { k: "cond", label: "Condition", hint: "Limits, IS 2026", pressed: condOn, disabled: !isLive, title: isLive ? "" : "The condition board is for the live transformer", act: () => openOnly("cond") },
  ];

  return (
    <div className={`page${V2 ? " v2" : " compact"}`}>
      {!V2 && <Frame />}
      <main className="sheet">
        <header className="strip-top">
          <SheetTabs mode={mode} onMode={(m) => { closeAll(); switchMode(m); }} />
          <div className="hdr-tools">
            {tools.map((t) => (
              <button key={t.k} className="explain" disabled={t.disabled} aria-pressed={t.pressed} title={t.title} onClick={t.act}>
                <span className="tab-label">{t.label}</span><span className="tab-hint">{t.hint}</span>
              </button>
            ))}
            <details className="export-menu">
              <summary className="explain"><span className="tab-label">Export</span><span className="tab-hint">Report, blueprint</span></summary>
              <div className="export-pop">
                <button disabled={!frames || !!exporting} onClick={doReport}>{exporting === "report" ? "Making the PDF…" : "Report (PDF with snapshot)"}</button>
                <a href="/api/blueprint.zip" download onClick={closeMenus}>Blueprint kit (.zip)</a>
                <a href="/api/blueprint.pdf" download onClick={closeMenus}>Blueprint drawings (.pdf)</a>
              </div>
            </details>
          </div>
          <button className="explain ask-btn" aria-pressed={chatOpen} onClick={() => openOnly("chat")}>
            <span className="tab-label">Ask</span><span className="tab-hint">The transformer</span>
          </button>
          <details className="hdr-more">
            <summary className="explain"><span className="tab-label">Tools</span></summary>
            <div className="export-pop">
              {tools.map((t) => <button key={t.k} disabled={t.disabled} title={t.title} onClick={() => { closeMenus(); t.act(); }}>{t.label}</button>)}
              <button disabled={!frames || !!exporting} onClick={doReport}>{exporting === "report" ? "Making the PDF…" : "Export: report (PDF with snapshot)"}</button>
              <a href="/api/blueprint.zip" download onClick={closeMenus}>Export: blueprint kit (.zip)</a>
              <a href="/api/blueprint.pdf" download onClick={closeMenus}>Export: blueprint drawings (.pdf)</a>
            </div>
          </details>
          <label className="dataset">
            <span className="dataset-label">Source</span>
            <select value={dataset} onChange={(e) => { closeAll(); setPinned([]); setMode("mirror"); setDataset(e.target.value); }}>
              <option value={LIVE}>Live transformer</option>
              <optgroup label="Replay datasets (recorded)">
                {(datasets.data ?? []).map((d) => (
                  <option key={d.dataset_id} value={d.dataset_id}>{d.name}</option>
                ))}
              </optgroup>
            </select>
          </label>
          <ImportData onLoaded={(id) => { setPinned([]); setMode("mirror"); setDataset(id); }} />
          {V2 && <V2Layers layers={layers} onToggle={(id) => setLayers((l) => ({ ...l, [id]: !l[id] }))} />}
          {V2 && (sim || info?.simulated) && <span className="v2-simpill">Simulated</span>}
          {V2 && <SectionToggle cut={cut} onCut={setCut} />}
        </header>
        <ChatDock dataset={dataset} open={chatOpen} onClose={() => setChatOpen(false)} />
        {liveOn && <div className="live-overlay"><Tablet onClose={() => { setLiveOn(false); if (frames) player.load(frames, replayT.current ?? undefined); }} /></div>}
        {condOn && isLive && <Condition onClose={() => setCondOn(false)} />}
        {circuit && <Circuit asset={(run.data?.asset as Record<string, unknown>) ?? null} onClose={() => setCircuit(false)} />}
        {bench && (
          <Workbench dataset={dataset} time={frames && i >= 0 ? frames.iso[i] : null} timeSeries={!!frames && !snapshot} snapshot={snapshot}
            onClose={() => setBench(false)} onSimulated={(id) => { setPinned([]); setMode("mirror"); setDataset(id); setBench(false); }} />
        )}
        <aside className="margin-left">
          {V2 ? <V2Left row={row} simulated={sim || !!info?.simulated} /> : (<>
            {sim ? <SimInputs w={wq.data} inp={simIn} onChange={setSimIn} dayLoaded={simDay} day={simDayState} />
              : <DataIn row={row} otiSuspect={otiSuspect} meterOnly={meterOnly} />}
            <LayerList layers={layers} onToggle={(id) => setLayers((l) => ({ ...l, [id]: !l[id] }))} />
            {frames && !sim && layers.lag && <LagTraces />}
            {live && layers.thermometer && !sim && <ThermalDiagram meterOnly={meterOnly && !sim} otiSuspect={otiSuspect} />}
            {live && <HeatScale meterOnly={meterOnly || sim} otiSuspect={otiSuspect} />}
          </>)}
        </aside>
        <div className={V2 ? "stage-v2" : "stage"}>
          {!V2 && live && <StageLeft />}
        <section className={"field" + (big ? " big" : "")} aria-label="Transformer-1, three-dimensional schematic">
          {!V2 && <ViewModes view={(cut ? "cut" : xray ? "xray" : "normal") as ViewMode} onView={(v) => { setCut(v === "cut"); setXray(v === "xray"); }} />}
          {!V2 && <button className="st-expand" aria-pressed={big} title={big ? "Back to the dashboard (Esc)" : "Expand the transformer view"} onClick={() => setBig(!big)}>{big ? "Close" : "Expand"}</button>}
          <Scene popover={!V2} popoverW={big ? 460 : 300} views={comp.data?.parts} fitTall={big ? 3.8 : 3.0} cut={cut} pinned={diag ? [] : pinned} data={calloutData}
            setPinned={sim ? () => {} : diag ? (ids) => setFocusPart(ids[ids.length - 1] ?? null) : setPinned}
            highlight={diag ? hl ?? (focusPart ? [focusPart] : []) : []} bubbleClass={bubbleClass}
            oilLevelPct={typeof oil === "number" ? oil : null} thermal={live} meterOnly={meterOnly && !sim} otiSuspect={otiSuspect}
            xray={xray} layers={layers} ratedW={sim ? (wq.data ? wq.data.params.P0_W + wq.data.params.Pk_W : null) : ratedW}
            reserveRight={panelOpen && V2 ? DETAIL_W : 0} bubbles={bubbles} markers={!diag}
            iRated={sim ? wq.data?.params.I_rated_A ?? null : params?.I_rated_A ?? null}
            events={sim ? [] : events as { timestamp: string }[]} />
          {V2 && live && layers.thermometer && <ThermalDiagram meterOnly={meterOnly && !sim} otiSuspect={otiSuspect} />}
          {V2 && diag && frames && <DiagnosePanel data={fq.data} loading={fq.isFetching} error={fq.error ? (fq.error as Error).message : null}
            focus={focusPart} onFocus={setHl} />}
          {V2 && frames && !sim && !diag && <Detail dataset={dataset} pinned={pinned} onClose={() => setPinned([])} />}
          {V2 && live && <HeatScale meterOnly={meterOnly || sim} otiSuspect={otiSuspect} />}
          {sim && simIn && !V2 && <SimPresets inp={simIn} onChange={setSimIn} />}
          {sim && <div className="sim-stamp" aria-label="Simulation, not measured data">Simulation</div>}
          {V2 && meterOnly && !sim && <p className="field-note">Meter-only data: no oil-temperature sensor. Temperatures are estimated by the twin.</p>}
          {V2 && snapshot && !sim && <p className="field-note">This dataset is a set of records with no time axis: there is nothing to replay.</p>}
          <TourCaption />
          {V2 && <p className="field-hint">Hover a part to read it. Click to pin. Drag to turn. Space plays, arrows step.</p>}
          {error && <p className="field-error" role="alert">{error}</p>}
        </section>
          {!V2 && live && <StageRight />}
          {!V2 && live && (sim ? <SimPhysics w={wq.data} inp={simIn} /> : diag
            ? <DiagnoseML dataset={dataset} iso={frames && i >= 0 ? frames.iso[i] : null} physicsCount={fq.data?.findings?.length ?? 0}
                physicsWorst={(fq.data?.findings ?? []).some((f) => f.severity === "critical") ? "critical" : (fq.data?.findings ?? []).some((f) => f.severity === "warning") ? "warning" : null} />
            : <StageTrends />)}
        </div>
        <aside className={"margin-right" + (sim ? " is-sim" : "")}>
          {V2 ? <V2Right dataset={dataset} iso={frames && i >= 0 ? frames.iso[i] : null} enabled={!!frames && !snapshot && !sim} sim={sim} /> : (<>
            {diag && frames && <DiagnosePanel data={fq.data} loading={fq.isFetching} error={fq.error ? (fq.error as Error).message : null}
              focus={focusPart} onFocus={setHl} />}
            <TwinState row={row} otiSuspect={otiSuspect} />
            {live && sim && <SimCalc w={wq.data} inp={simIn} />}
            {live && layers.heatflow && !sim && <HeatBalance />}
            {V2 && live && layers.powerflow && <PowerFlowReadout />}
            {meterOnly && !sim && <p className="field-note side-note">Meter-only data: no oil-temperature sensor. Temperatures are estimated by the twin.</p>}
            {snapshot && !sim && <p className="field-note side-note">This dataset is a set of records with no time axis: there is nothing to replay.</p>}
            {!sim && <p className="side-note hint">Hover a part to read it. Click to pin. Drag to turn. Space plays, arrows step.</p>}
            {live && layers.lifeclock && !sim && <LifeClock meterOnly={meterOnly && !sim} perDay={sim && !simDay} />}
          </>)}
        </aside>
        <footer className="strip-bottom">
          {sim && simIn
            ? <SimControls inp={simIn} onChange={setSimIn} w={wq.data} busy={wq.isFetching} error={wq.error ? (wq.error as Error).message : null}
                dayBusy={simDayState.busy} />
            : <Timeline frames={frames} alerts={alerts} events={events} meterOnly={meterOnly} />}
          {!V2 && <TitleBlock run={run.data} time={sim ? "simulated" : frames && i >= 0 ? frames.iso[i] : null}
            simulated={info?.simulated ?? false} />}
        </footer>
      </main>
    </div>
  );
}
