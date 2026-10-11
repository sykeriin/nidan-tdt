// The drawing field: orthographic camera (parallel lines, like a GA drawing), matte light, no shadows.
// Callouts are an HTML/SVG layer over the canvas, positioned from projected anchors.
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Transformer, TwinContext } from "./Transformer";
import { AnchorTracker, CalloutLayer, type Anchors, type CalloutData } from "./Callout";
import { ThermalDriver, ThermalMarkers, TwinGhost } from "./Thermal";
import { OilFlow } from "./OilFlow";
import { Electrical, ThroughFaults } from "./Electrical";
import { PowerFlow } from "./PowerFlow";
import { CameraTour } from "./Tour";
import { HeatFlow } from "./HeatFlow";
import { ALL_ON, type Layers } from "./layers";
import type { PartId } from "./parts";
import type { PartView } from "../api/client";

function FitZoom({ tall }: { tall: number }) {
  const { camera, size } = useThree();
  useEffect(() => {
    camera.zoom = Math.min(size.width / 4.2, size.height / tall);
    camera.updateProjectionMatrix();
  }, [camera, size, tall]);
  return null;
}

export function Scene({ cut, pinned, setPinned, data, oilLevelPct, thermal = false, meterOnly = false, otiSuspect = false,
  layers = ALL_ON, ratedW = null, reserveRight = 0, xray = false, fitTall = 3.0, popover = false, views, bubbles, bubbleClass, highlight = [], markers = true, iRated = null, events = [] }: {
  bubbleClass?: Partial<Record<PartId, string>>;
  highlight?: PartId[];
  markers?: boolean;
  iRated?: number | null;
  events?: { timestamp: string; peak_pu?: number; duration_ms?: number; phase?: string }[]; // hot-spot and residual tags (off in Diagnose, where the finding numbers take their place)
  bubbles?: Partial<Record<PartId, string>>;
  otiSuspect?: boolean;
  layers?: Layers;
  ratedW?: number | null;
  reserveRight?: number;
  xray?: boolean;
  popover?: boolean;
  views?: Partial<Record<PartId, PartView>>;
  fitTall?: number; // scene height (world units) the view fits: larger leaves more room around the model
  thermal?: boolean;
  meterOnly?: boolean;
  cut: boolean;
  pinned: PartId[];
  setPinned: (ids: PartId[]) => void;
  data: CalloutData;
  oilLevelPct: number | null;
}) {
  const [hovered, setHovered] = useState<PartId | null>(null);
  const [anchors, setAnchors] = useState<Anchors>({});
  const box = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ w: 0, h: 0, field: undefined as DOMRect | undefined, sheet: undefined as DOMRect | undefined });
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => setDims({
      w: el.clientWidth, h: el.clientHeight, field: el.getBoundingClientRect(),
      sheet: el.closest(".sheet")?.getBoundingClientRect(),
    });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const active = useMemo(() => new Set<PartId>([...pinned, ...highlight, ...(hovered ? [hovered] : [])]), [pinned, hovered, highlight]);
  const ctx = useMemo(() => ({
    active,
    onOver: (id: PartId) => setHovered(id),
    onOut: (id: PartId) => setHovered((h) => (h === id ? null : h)),
    onClick: (id: PartId) => setPinned(pinned.includes(id) ? pinned.filter((p) => p !== id) : [...pinned, id]),
    xray,
  }), [active, pinned, setPinned, xray]);
  const bubbleKey = Object.keys(bubbles ?? {}).join(",");
  const shown = useMemo(() => [...new Set([...pinned, ...(hovered ? [hovered] : [])])], [pinned, hovered]);
  const tracked = useMemo(() => [...new Set([...shown, ...(bubbleKey ? bubbleKey.split(",") as PartId[] : [])])], [shown, bubbleKey]);

  return (
    <div className="scene" ref={box}>
      <Canvas
        orthographic
        camera={{ position: [6.2, 4.4, 7.4], zoom: 140, near: -50, far: 100 }}
        gl={{ antialias: true, alpha: true }}
        dpr={[1, 2]}
        onPointerMissed={() => setHovered(null)}
      >
        <FitZoom tall={fitTall} />
        <hemisphereLight args={["#FBF8F0", "#3A3A36", 0.6]} />
        <directionalLight position={[4, 9, 6]} intensity={1.3} />
        <directionalLight position={[-6, 3, -3]} intensity={0.35} />
        <TwinContext.Provider value={ctx}>
          <Transformer cut={cut} oilLevelPct={oilLevelPct} thermal={thermal && layers.temperature} />
        </TwinContext.Provider>
        {thermal && <>
          {layers.temperature && <ThermalDriver otiSuspect={otiSuspect} />}
          {layers.ghost && <TwinGhost otiSuspect={otiSuspect} />}
          {markers && <ThermalMarkers meterOnly={meterOnly} otiSuspect={otiSuspect} />}
          {layers.oilflow && <OilFlow cut={cut || active.has("tank")} otiSuspect={otiSuspect} />}
          {layers.heatflow && markers && <HeatFlow ratedW={ratedW} />}
          {layers.powerflow && <PowerFlow iRated={iRated} />}
          {layers.electrical && <Electrical iRated={iRated} />}
          {layers.faults && events.length > 0 && <ThroughFaults events={events} />}
        </>}
        <AnchorTracker ids={tracked} onChange={setAnchors} />
        <CameraTour />
        <OrbitControls makeDefault target={[0.1, 1.6, 0]} enableDamping dampingFactor={0.12} minZoom={60} maxZoom={600}
          maxPolarAngle={Math.PI * 0.49} />
      </Canvas>
      <CalloutLayer shown={shown} pinned={pinned} anchors={anchors} data={data} width={Math.max(0, dims.w - reserveRight)} height={dims.h}
        fieldRect={dims.field} sheetRect={dims.sheet} bubbles={bubbles} bubbleClass={bubbleClass} popover={popover} views={views}
        onUnpin={(id) => setPinned(pinned.filter((p) => p !== id))} />
    </div>
  );
}
