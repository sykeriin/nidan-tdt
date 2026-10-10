import { useEffect, useMemo, useRef, useState } from "react";
import { Scene } from "./twin/Scene";
import { PART, type PartId } from "./twin/parts";
import { HeatScale } from "./twin/HeatScale";
import { DataIn, Frame, SectionToggle, SheetTabs, TitleBlock, TwinState, type TwinMode } from "./sheet/Sheet";
import { Timeline } from "./sheet/Timeline";
import { useDatasets, useFindings, useFramesQuery, useRunSummary, useThermalParams, useWhatIf, type Alert, type WhatIfInput } from "./api/client";
import { DiagnosePanel, findingMarks } from "./sheet/Diagnose";
import { TourCaption, tour, useTourStep } from "./twin/Tour";
import { SimControls, SimInputs, whatIfFrames } from "./sheet/Simulate";
import { ThermalDiagram } from "./sheet/ThermalDiagram";
import { LagTraces } from "./sheet/LagTraces";
import { LayerList } from "./sheet/LayerList";
import { Detail, detailLetter } from "./sheet/Detail";
import { HeatBalance } from "./sheet/HeatBalance";
import { ImportData } from "./sheet/ImportData";
import { LifeClock } from "./twin/LifeClock";
import { ALL_ON, type Layers } from "./twin/layers";
import { player, usePlayerIndex, type Frames } from "./player/player";

// URL parameters make any view reproducible: ?ds=S2&t=2026-04-25T12:00&pin=winding-Y,oti&cut=0&play=1&mode=simulate
const q = new URLSearchParams(window.location.search);
const DETAIL_W = 330; // px, must match .detail width in index.css
const INITIAL_PINS = (q.get("pin") ?? "").split(",").filter((p): p is PartId => p in PART);

export default function App() {
  const [dataset, setDataset] = useState(q.get("ds") ?? "S2");
  const [cut, setCut] = useState(q.get("cut") !== "0");
  const [mode, setMode] = useState<TwinMode>("mirror");
  const [pinned, setPinned] = useState<PartId[]>(INITIAL_PINS);
  const [layers, setLayers] = useState<Layers>(ALL_ON);
  const touring = useTourStep() >= 0;

  const datasets = useDatasets();
  const info = datasets.data?.find((d) => d.dataset_id === dataset);
  const run = useRunSummary(dataset);
  const snapshot = run.data?.mode === "snapshot";
  const framesQ = useFramesQuery(dataset, run.isSuccess && !snapshot);
  const meterOnly = run.data?.mode === "meter_only";
  const otiSuspect = (run.data?.summary as Record<string, any> | undefined)?.plausibility?.OTI_C === "suspect";

  const frames: Frames | null = useMemo(() => {
    const d = framesQ.data;
    if (!d) return null;
    return { dataset, iso: d.timestamp, t: d.timestamp.map((s) => Date.parse(s)), cols: d.columns as Frames["cols"] };
  }, [framesQ.data, dataset]);

  useEffect(() => {
    if (!frames) return;
    const t0 = q.get("t") && dataset === (q.get("ds") ?? "S2") ? Date.parse(q.get("t")!) : undefined;
    player.load(frames, Number.isNaN(t0) ? undefined : t0);
    if (q.get("play") === "1") player.play();
    return () => player.pause();
  }, [frames, dataset]);

  // ---- SIMULATE: the what-if answer is loaded into the replay clock as a one-row frame
  const sim = mode === "simulate";
  const [simIn, setSimIn] = useState<WhatIfInput | null>(null);
  const [simFrom, setSimFrom] = useState<string | null>(null);
  const replayT = useRef<number | null>(null);
  const wq = useWhatIf(sim ? simIn : null, dataset, simFrom);
  useEffect(() => { if (sim && wq.data) player.load(whatIfFrames(wq.data, dataset)); }, [sim, wq.data, dataset]);
  const clamp = (v: unknown, lo: number, hi: number, dflt: number) =>
    typeof v === "number" ? Math.min(hi, Math.max(lo, v)) : dflt;
  const switchMode = (m: TwinMode) => {
    if (m === mode) return;
    if (m === "simulate") {
      const r = player.frames && !player.frames.dataset.endsWith("#sim") ? player.row() : {};
      replayT.current = player.t;
      setSimFrom(frames && player.index >= 0 ? frames.iso[player.index] : null);
      // start from what the transformer is doing at the cursor (cooling: the measured radiator effectiveness)
      setSimIn({ load: Math.round(clamp(r.load_pu, 0.3, 1.4, 0.75) * 100) / 100, ambient: Math.round(clamp(r.amb_C, 15, 50, 30) * 2) / 2,
        cooling: Math.round(clamp(r.radiator_effectiveness, 0.5, 1, 1) * 100) / 100 });
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
      setSimIn((cur) => cur && { load: n("load") ?? cur.load, ambient: n("amb") ?? cur.ambient, cooling: n("cool") ?? cur.cooling });
    }
  }, [frames]); // eslint-disable-line react-hooks/exhaustive-deps

  const i = usePlayerIndex();
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
    : frames && !sim ? Object.fromEntries(pinned.map((id) => [id, detailLetter(pinned, id)])) : undefined;
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

  return (
    <div className="page">
      <Frame />
      <main className="sheet">
        <header className="strip-top">
          <SheetTabs mode={mode} onMode={switchMode} />
          <button className="explain" disabled={!frames} aria-pressed={touring}
            onClick={() => { if (touring) { tour.stop(); return; } switchMode("mirror"); setPinned([]); setCut(true); setLayers(ALL_ON); tour.start(); }}>
            <span className="tab-label">{touring ? "Stop tour" : "Explain"}</span><span className="tab-hint">60 s guided tour</span>
          </button>
          <label className="dataset">
            <span className="dataset-label">Dataset</span>
            <select value={dataset} onChange={(e) => { setPinned([]); setMode("mirror"); setDataset(e.target.value); }}>
              {(datasets.data ?? []).map((d) => (
                <option key={d.dataset_id} value={d.dataset_id}>{d.name}</option>
              ))}
            </select>
          </label>
          <ImportData onLoaded={(id) => { setPinned([]); setMode("mirror"); setDataset(id); }} />
          <SectionToggle cut={cut} onCut={setCut} />
        </header>
        <aside className="margin-left">
          {sim ? <SimInputs w={wq.data} /> : <DataIn row={row} otiSuspect={otiSuspect} meterOnly={meterOnly} />}
          <LayerList layers={layers} onToggle={(id) => setLayers((l) => ({ ...l, [id]: !l[id] }))} />
          {frames && !sim && layers.lag && <LagTraces />}
        </aside>
        <section className="field" aria-label="Transformer-1, three-dimensional schematic">
          <Scene cut={cut} pinned={diag ? [] : pinned} data={calloutData}
            setPinned={sim ? () => {} : diag ? (ids) => setFocusPart(ids[ids.length - 1] ?? null) : setPinned}
            highlight={diag ? hl ?? (focusPart ? [focusPart] : []) : []} bubbleClass={bubbleClass}
            oilLevelPct={typeof oil === "number" ? oil : null} thermal={live} meterOnly={meterOnly && !sim} otiSuspect={otiSuspect}
            layers={layers} ratedW={sim ? (wq.data ? wq.data.params.P0_W + wq.data.params.Pk_W : null) : ratedW}
            reserveRight={panelOpen ? DETAIL_W : 0} bubbles={bubbles} markers={!diag}
            iRated={sim ? wq.data?.params.I_rated_A ?? null : params?.I_rated_A ?? null}
            events={sim ? [] : events as { timestamp: string }[]} />
          {live && layers.thermometer && <ThermalDiagram meterOnly={meterOnly && !sim} otiSuspect={otiSuspect} />}
          {live && layers.heatflow && !panelOpen && <HeatBalance />}
          {diag && frames && <DiagnosePanel data={fq.data} loading={fq.isFetching} error={fq.error ? (fq.error as Error).message : null}
            focus={focusPart} onFocus={setHl} />}
          {frames && !sim && !diag && <Detail dataset={dataset} pinned={pinned} onClose={() => setPinned([])} />}
          {live && <HeatScale meterOnly={meterOnly || sim} otiSuspect={otiSuspect} />}
          {sim && <div className="sim-stamp" aria-label="Simulation, not measured data">Simulation</div>}
          {meterOnly && !sim && <p className="field-note">Meter-only data: no oil-temperature sensor. Temperatures are estimated by the twin.</p>}
          {snapshot && !sim && <p className="field-note">This dataset is a set of records with no time axis: there is nothing to replay.</p>}
          <TourCaption />
          <p className="field-hint">Hover a part to read it. Click to pin. Drag to turn. Space plays, arrows step.</p>
          {error && <p className="field-error" role="alert">{error}</p>}
        </section>
        <aside className="margin-right">
          <TwinState row={row} otiSuspect={otiSuspect} />
          {live && layers.lifeclock && <LifeClock meterOnly={meterOnly && !sim} perDay={sim} />}
        </aside>
        <footer className="strip-bottom">
          {sim && simIn
            ? <SimControls inp={simIn} onChange={setSimIn} w={wq.data} busy={wq.isFetching} error={wq.error ? (wq.error as Error).message : null} />
            : <Timeline frames={frames} alerts={alerts} events={events} meterOnly={meterOnly} />}
          <TitleBlock run={run.data} time={sim ? "simulated" : frames && i >= 0 ? frames.iso[i] : null}
            simulated={info?.simulated ?? false} />
        </footer>
      </main>
    </div>
  );
}
