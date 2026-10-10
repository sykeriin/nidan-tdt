import { useEffect, useMemo, useState } from "react";
import { Scene } from "./twin/Scene";
import { PART, type PartId } from "./twin/parts";
import { HeatScale } from "./twin/HeatScale";
import { DataIn, Frame, SectionToggle, SheetTabs, TitleBlock, TwinState, type TwinMode } from "./sheet/Sheet";
import { Timeline } from "./sheet/Timeline";
import { useDatasets, useFramesQuery, useRunSummary, useThermalParams, type Alert } from "./api/client";
import { ThermalDiagram } from "./sheet/ThermalDiagram";
import { LagTraces } from "./sheet/LagTraces";
import { LayerList } from "./sheet/LayerList";
import { Detail, detailLetter } from "./sheet/Detail";
import { ALL_ON, type Layers } from "./twin/layers";
import { player, usePlayerIndex, type Frames } from "./player/player";

// URL parameters make any view reproducible: ?ds=S2&t=2026-04-25T12:00&pin=winding-Y,oti&cut=0&play=1
const q = new URLSearchParams(window.location.search);
const DETAIL_W = 330; // px, must match .detail width in index.css
const INITIAL_PINS = (q.get("pin") ?? "").split(",").filter((p): p is PartId => p in PART);

export default function App() {
  const [dataset, setDataset] = useState(q.get("ds") ?? "S2");
  const [cut, setCut] = useState(q.get("cut") !== "0");
  const [mode, setMode] = useState<TwinMode>("mirror");
  const [pinned, setPinned] = useState<PartId[]>(INITIAL_PINS);
  const [layers, setLayers] = useState<Layers>(ALL_ON);

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

  const i = usePlayerIndex();
  const params = useThermalParams(dataset, frames?.iso[0] ?? null).data;
  const ratedW = params ? params.P0_W + params.Pk_W : null; // arrow-width scale only
  const row = useMemo(() => (frames && i >= 0 ? player.row(i) : null), [frames, i]);
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
          <SheetTabs mode={mode} onMode={setMode} />
          <label className="dataset">
            <span className="dataset-label">Dataset</span>
            <select value={dataset} onChange={(e) => { setPinned([]); setDataset(e.target.value); }}>
              {(datasets.data ?? []).map((d) => (
                <option key={d.dataset_id} value={d.dataset_id}>{d.name}</option>
              ))}
            </select>
          </label>
          <SectionToggle cut={cut} onCut={setCut} />
        </header>
        <aside className="margin-left">
          <DataIn row={row} otiSuspect={otiSuspect} meterOnly={meterOnly} />
          <LayerList layers={layers} onToggle={(id) => setLayers((l) => ({ ...l, [id]: !l[id] }))} />
          {frames && layers.lag && <LagTraces />}
        </aside>
        <section className="field" aria-label="Transformer-1, three-dimensional schematic">
          <Scene cut={cut} pinned={pinned} setPinned={setPinned} data={calloutData}
            oilLevelPct={typeof oil === "number" ? oil : null} thermal={!!frames} meterOnly={meterOnly} otiSuspect={otiSuspect}
            layers={layers} ratedW={ratedW} reserveRight={pinned.length && frames ? DETAIL_W : 0}
            bubbles={frames ? Object.fromEntries(pinned.map((id) => [id, detailLetter(pinned, id)])) : undefined} />
          {frames && layers.thermometer && <ThermalDiagram meterOnly={meterOnly} otiSuspect={otiSuspect} />}
          {frames && <Detail dataset={dataset} pinned={pinned} onClose={() => setPinned([])} />}
          {frames && <HeatScale meterOnly={meterOnly} otiSuspect={otiSuspect} />}
          {meterOnly && <p className="field-note">Meter-only data: no oil-temperature sensor. Temperatures are estimated by the twin.</p>}
          {snapshot && <p className="field-note">This dataset is a set of records with no time axis: there is nothing to replay.</p>}
          <p className="field-hint">Hover a part to read it. Click to pin. Drag to turn. Space plays, arrows step.</p>
          {error && <p className="field-error" role="alert">{error}</p>}
        </section>
        <aside className="margin-right"><TwinState row={row} otiSuspect={otiSuspect} /></aside>
        <footer className="strip-bottom">
          <Timeline frames={frames} alerts={alerts} events={events} meterOnly={meterOnly} />
          <TitleBlock run={run.data} time={frames && i >= 0 ? frames.iso[i] : null}
            simulated={info?.simulated ?? false} />
        </footer>
      </main>
    </div>
  );
}
