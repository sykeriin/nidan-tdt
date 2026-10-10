// Procedural Transformer-1: every part is a hoverable group drawn as a matte solid with ink edges.
// Dimensions are schematic (metres-ish), not to scale. Geometry only: no engineering values computed here.
import { createContext, useContext, useMemo, type ReactNode } from "react";
import { Edges } from "@react-three/drei";
import * as THREE from "three";
import type { ThreeEvent } from "@react-three/fiber";
import type { PartId } from "./parts";
import { INK } from "../theme";

// ---------------------------------------------------------------- materials (matte, no gloss)
const mat = (color: string, extra: Partial<THREE.MeshStandardMaterialParameters> = {}) =>
  new THREE.MeshStandardMaterial({ color, roughness: 0.92, metalness: 0.04, ...extra });
const M = {
  tank: mat("#9A9C96"),
  tankInside: mat("#B9B8AF", { side: THREE.BackSide }),
  radiator: mat("#6F726C"),
  core: mat("#55585A"),
  lv: mat("#B06A3A"),
  hv: mat("#A47A4F"),
  porcelain: mat("#F3F0E6"),
  metalDark: mat("#4A4C48"),
  glass: mat("#D6E2E4", { transparent: true, opacity: 0.38, depthWrite: false }),
  oilFill: mat("#B8893A", { transparent: true, opacity: 0.85 }),
  oil: mat("#C9A24F", { transparent: true, opacity: 0.13, depthWrite: false }),
  silica: mat("#8E9EA8"),
  plate: mat("#CFC9B8"),
  skid: mat("#5C5E5A"),
};
type MatKey = keyof typeof M;
// hovering or pinning the tank turns its steel to faint glass, so the oil, windings and circulation show inside
const TANK_GLASS = mat("#9A9C96", { transparent: true, opacity: 0.12, depthWrite: false });
// Heat materials: recoloured every frame by ThermalDriver (Thermal.tsx) from the replay clock, never by React.
export const HEAT_MATS = {
  winding: { R: mat("#B06A3A"), Y: mat("#B06A3A"), B: mat("#B06A3A") },
  oil: mat("#C9A24F", { transparent: true, opacity: 0.24, depthWrite: false }),
};
// active (hovered or pinned) parts take a faint blueprint wash, like a highlighted region on a drawing
const ACTIVE: Record<MatKey, THREE.MeshStandardMaterial> = Object.fromEntries(
  Object.entries(M).map(([k, m]) => {
    const c = m.clone();
    c.emissive = new THREE.Color("#2457A6");
    c.emissiveIntensity = 0.07;
    return [k, c];
  }),
) as Record<MatKey, THREE.MeshStandardMaterial>;

// ---------------------------------------------------------------- interaction context
interface TwinCtx {
  active: Set<PartId>;
  onOver: (id: PartId) => void;
  onOut: (id: PartId) => void;
  onClick: (id: PartId) => void;
  xray?: boolean; // see-through steel: the oil, windings and core show through the tank walls
}
export const TwinContext = createContext<TwinCtx>({ active: new Set(), onOver: () => {}, onOut: () => {}, onClick: () => {} });
const PartCtx = createContext<PartId | null>(null);

function Part({ id, children }: { id: PartId; children: ReactNode }) {
  const { onOver, onOut, onClick } = useContext(TwinContext);
  return (
    <group
      onPointerOver={(e: ThreeEvent<PointerEvent>) => { e.stopPropagation(); onOver(id); document.body.style.cursor = "crosshair"; }}
      onPointerOut={(e: ThreeEvent<PointerEvent>) => { e.stopPropagation(); onOut(id); document.body.style.cursor = ""; }}
      onClick={(e: ThreeEvent<MouseEvent>) => { e.stopPropagation(); onClick(id); }}
    >
      <PartCtx.Provider value={id}>{children}</PartCtx.Provider>
    </group>
  );
}

interface MeshProps {
  geo: THREE.BufferGeometry;
  m: MatKey;
  p?: [number, number, number];
  r?: [number, number, number];
  edges?: number | false; // edge threshold angle (deg); false = no ink edges
  hit?: boolean; // false: not pickable (e.g. translucent oil volume)
  visible?: boolean;
  override?: THREE.Material; // thermal layer: heat material instead of the part's base material
}
function Mesh({ geo, m, p = [0, 0, 0], r = [0, 0, 0], edges = 25, hit = true, visible = true, override }: MeshProps) {
  const id = useContext(PartCtx);
  const { active } = useContext(TwinContext);
  const on = id !== null && active.has(id);
  const { xray } = useContext(TwinContext);
  const glass = m === "tank" && (xray === true || (id === "tank" && on));
  return (
    <mesh geometry={geo} material={override ?? (glass ? TANK_GLASS : on ? ACTIVE[m] : M[m])} position={p} rotation={r} visible={visible}
      raycast={hit ? undefined : () => null}>
      {edges !== false && <Edges threshold={edges} color={INK} transparent opacity={glass ? 0.35 : 1} />}
    </mesh>
  );
}

// ---------------------------------------------------------------- geometry helpers (cached)
const cache = new Map<string, THREE.BufferGeometry>();
const box = (w: number, h: number, d: number) => {
  const k = `b${w},${h},${d}`;
  if (!cache.has(k)) cache.set(k, new THREE.BoxGeometry(w, h, d));
  return cache.get(k)!;
};
const cyl = (r: number, h: number, seg = 40) => {
  const k = `c${r},${h},${seg}`;
  if (!cache.has(k)) cache.set(k, new THREE.CylinderGeometry(r, r, h, seg));
  return cache.get(k)!;
};
const tube = (rIn: number, rOut: number, h: number) => {
  const k = `t${rIn},${rOut},${h}`;
  if (!cache.has(k)) {
    const pts = [
      new THREE.Vector2(rIn, -h / 2), new THREE.Vector2(rOut, -h / 2), new THREE.Vector2(rOut, h / 2),
      new THREE.Vector2(rIn, h / 2), new THREE.Vector2(rIn, -h / 2),
    ];
    cache.set(k, new THREE.LatheGeometry(pts, 56));
  }
  return cache.get(k)!;
};
const torus = (r: number, t: number) => {
  const k = `o${r},${t}`;
  if (!cache.has(k)) cache.set(k, new THREE.TorusGeometry(r, t, 12, 40));
  return cache.get(k)!;
};

// ---------------------------------------------------------------- dimensions
const W = 1.8, H = 1.4, D = 1.1, Y0 = 0.15, T = 0.03; // tank
const TOP = Y0 + H; // cover level
const LIMBS: Record<"R" | "Y" | "B", number> = { R: -0.55, Y: 0, B: 0.55 };
const XQ: [number, number, number] = [Math.PI / 2, 0, 0]; // lay a Y-axis primitive along Z
const ZQ: [number, number, number] = [0, 0, Math.PI / 2]; // lay it along X

function Bushing({ x, z, h, shedR, sheds, bodyR }: { x: number; z: number; h: number; shedR: number; sheds: number; bodyR: number }) {
  const base = TOP + 0.02;
  return (
    <>
      <Mesh geo={cyl(bodyR + 0.03, 0.04)} m="metalDark" p={[x, base, z]} />
      <Mesh geo={cyl(bodyR, h)} m="porcelain" p={[x, base + 0.02 + h / 2, z]} edges={60} />
      {Array.from({ length: sheds }, (_, i) => (
        <Mesh key={i} geo={cyl(shedR, 0.012)} m="porcelain" p={[x, base + 0.06 + i * ((h - 0.08) / Math.max(sheds - 1, 1)), z]} />
      ))}
      <Mesh geo={cyl(bodyR * 0.7, 0.06)} m="metalDark" p={[x, base + 0.05 + h, z]} />
      <Mesh geo={cyl(0.012, 0.07)} m="metalDark" p={[x, base + 0.11 + h, z]} />
    </>
  );
}

export { tube, LIMBS, Y0, H, W, D, T };

export function Transformer({ cut, oilLevelPct, thermal = false }: { cut: boolean; oilLevelPct: number | null; thermal?: boolean }) {
  const oilMat = thermal ? HEAT_MATS.oil : undefined;
  const front = !cut; // pieces in front of the section plane (z > 0)
  const oilH = H - 0.1;
  const gaugeFill = useMemo(() => Math.max(0.02, Math.min(1, (oilLevelPct ?? 0) / 100)), [oilLevelPct]);

  return (
    <group>
      <Part id="tank">
        {/* skid */}
        <Mesh geo={box(2.0, 0.12, 0.14)} m="skid" p={[0, 0.06, 0.38]} />
        <Mesh geo={box(2.0, 0.12, 0.14)} m="skid" p={[0, 0.06, -0.38]} />
        {/* back wall + inner face */}
        <Mesh geo={box(W, H, T)} m="tank" p={[0, Y0 + H / 2, -D / 2 + T / 2]} />
        {/* side walls, split at the section plane */}
        {([-1, 1] as const).map((s) => (
          <group key={s}>
            <Mesh geo={box(T, H, D / 2)} m="tank" p={[s * (W / 2 - T / 2), Y0 + H / 2, -D / 4]} />
            <Mesh geo={box(T, H, D / 2)} m="tank" p={[s * (W / 2 - T / 2), Y0 + H / 2, D / 4]} visible={front} />
          </group>
        ))}
        {/* cover and bottom, split */}
        <Mesh geo={box(W + 0.06, T, D / 2 + 0.03)} m="tank" p={[0, TOP, -D / 4 - 0.015]} />
        <Mesh geo={box(W + 0.06, T, D / 2 + 0.03)} m="tank" p={[0, TOP, D / 4 + 0.015]} visible={front} />
        <Mesh geo={box(W, T, D)} m="tank" p={[0, Y0 + T / 2, 0]} />
        {/* front wall: whole when closed; only a low plinth band when sectioned */}
        <Mesh geo={box(W, H, T)} m="tank" p={[0, Y0 + H / 2, D / 2 - T / 2]} visible={front} />
        <Mesh geo={box(W, 0.26, T)} m="tank" p={[0, Y0 + 0.13, D / 2 - T / 2]} visible={cut} />
      </Part>

      <Part id="oil">
        <Mesh geo={box(W - 2 * T, oilH, D / 2 - T)} m="oil" p={[0, Y0 + oilH / 2, -D / 4 + T / 2]} edges={false} hit={false} override={oilMat} />
        <Mesh geo={box(W - 2 * T, oilH, D / 2 - T)} m="oil" p={[0, Y0 + oilH / 2, D / 4 - T / 2]} edges={false} hit={false} visible={front} override={oilMat} />
        {/* the oil surface is the oil's pick target, so windings stay hoverable through the volume */}
        <Mesh geo={box(W - 2 * T, 0.03, cut ? D / 2 - T : D - 2 * T)} m="oil" p={[0, Y0 + oilH, cut ? -D / 4 + T / 2 : 0]} edges={20} />
      </Part>

      <Part id="core">
        {Object.values(LIMBS).map((x) => (
          <Mesh key={x} geo={box(0.16, 0.8, 0.16)} m="core" p={[x, 0.85, 0]} />
        ))}
        <Mesh geo={box(1.42, 0.16, 0.16)} m="core" p={[0, 0.37, 0]} />
        <Mesh geo={box(1.42, 0.16, 0.16)} m="core" p={[0, 1.33, 0]} />
      </Part>

      {(Object.entries(LIMBS) as ["R" | "Y" | "B", number][]).map(([ph, x]) => (
        <Part key={ph} id={`winding-${ph}` as PartId}>
          <Mesh geo={tube(0.095, 0.15, 0.74)} m="lv" p={[x, 0.85, 0]} edges={40} override={thermal ? HEAT_MATS.winding[ph] : undefined} />
          <Mesh geo={tube(0.165, 0.235, 0.76)} m="hv" p={[x, 0.85, 0]} edges={40} override={thermal ? HEAT_MATS.winding[ph] : undefined} />
        </Part>
      ))}

      <Part id="radiators">
        {([-1, 1] as const).map((s) => (
          <group key={s}>
            {Array.from({ length: 8 }, (_, i) => (
              <Mesh key={i} geo={box(0.36, 1.0, 0.022)} m="radiator" p={[s * (W / 2 + 0.26), Y0 + 0.7, -0.42 + i * 0.12]} />
            ))}
            <Mesh geo={cyl(0.035, 0.96)} m="radiator" p={[s * (W / 2 + 0.26), Y0 + 1.24, 0]} r={XQ} />
            <Mesh geo={cyl(0.035, 0.96)} m="radiator" p={[s * (W / 2 + 0.26), Y0 + 0.16, 0]} r={XQ} />
            <Mesh geo={cyl(0.03, 0.26)} m="radiator" p={[s * (W / 2 + 0.11), Y0 + 1.24, 0]} r={ZQ} />
            <Mesh geo={cyl(0.03, 0.26)} m="radiator" p={[s * (W / 2 + 0.11), Y0 + 0.16, 0]} r={ZQ} />
          </group>
        ))}
      </Part>

      <Part id="conservator">
        <Mesh geo={cyl(0.2, 1.3, 48)} m="tank" p={[0, 2.25, -0.5]} r={ZQ} edges={30} />
        <Mesh geo={box(0.06, 0.5, 0.06)} m="tank" p={[-0.45, TOP + 0.25, -0.5]} />
        <Mesh geo={box(0.06, 0.5, 0.06)} m="tank" p={[0.45, TOP + 0.25, -0.5]} />
        <Mesh geo={cyl(0.028, 0.5)} m="tank" p={[0.2, TOP + 0.25, -0.42]} />
        <Mesh geo={box(0.1, 0.08, 0.08)} m="metalDark" p={[0.2, TOP + 0.26, -0.42]} />
      </Part>

      <Part id="oil-gauge">
        <Mesh geo={box(0.03, 0.04, 0.04)} m="metalDark" p={[0.67, 2.38, -0.5]} />
        <Mesh geo={box(0.03, 0.04, 0.04)} m="metalDark" p={[0.67, 2.12, -0.5]} />
        <Mesh geo={cyl(0.035, 0.26, 24)} m="glass" p={[0.71, 2.25, -0.5]} edges={60} />
        <Mesh geo={cyl(0.027, 0.24 * gaugeFill, 24)} m="oilFill" p={[0.71, 2.13 + (0.24 * gaugeFill) / 2, -0.5]} edges={false} />
      </Part>

      <Part id="breather">
        <Mesh geo={cyl(0.018, 0.4)} m="metalDark" p={[-0.74, 2.05, -0.5]} />
        <Mesh geo={box(0.12, 0.03, 0.03)} m="metalDark" p={[-0.69, 2.25, -0.5]} />
        <Mesh geo={cyl(0.06, 0.24, 28)} m="silica" p={[-0.74, 1.74, -0.5]} edges={60} />
        <Mesh geo={cyl(0.045, 0.05, 28)} m="metalDark" p={[-0.74, 1.6, -0.5]} />
      </Part>

      <Part id="hv-bushings">
        {[-0.5, 0, 0.5].map((x) => (
          <Bushing key={x} x={x} z={-0.15} h={0.55} bodyR={0.045} shedR={0.088} sheds={7} />
        ))}
      </Part>

      {(["R", "Y", "B", "N"] as const).map((ph, i) => (
        <Part key={ph} id={`lv-${ph}` as PartId}>
          <Bushing x={-0.45 + i * 0.3} z={0.3} h={0.26} bodyR={0.04} shedR={0.066} sheds={3} />
        </Part>
      ))}

      <Part id="cts">
        {[-0.45, -0.15, 0.15].map((x) => (
          <Mesh key={x} geo={torus(0.068, 0.016)} m="metalDark" p={[x, TOP + 0.08, 0.3]} r={XQ} edges={false} />
        ))}
      </Part>

      <Part id="oti">
        <Mesh geo={cyl(0.03, 0.07)} m="metalDark" p={[0.72, TOP + 0.05, 0.36]} />
        <Mesh geo={cyl(0.012, 0.18)} m="metalDark" p={[0.72, TOP + 0.13, 0.36]} />
        <Mesh geo={cyl(0.05, 0.025)} m="plate" p={[0.72, TOP + 0.23, 0.36]} />
      </Part>

      <Part id="ambient">
        <Mesh geo={cyl(0.02, 1.3)} m="metalDark" p={[1.75, 0.65, 0.75]} />
        <Mesh geo={box(0.18, 0.2, 0.18)} m="porcelain" p={[1.75, 1.4, 0.75]} />
        {[0, 1, 2].map((i) => (
          <Mesh key={i} geo={box(0.2, 0.012, 0.2)} m="porcelain" p={[1.75, 1.33 + i * 0.07, 0.75]} />
        ))}
      </Part>

      <Part id="nameplate">
        <Mesh geo={box(0.32, 0.16, 0.008)} m="plate" p={[-0.4, Y0 + 0.13, D / 2 + 0.005]} />
      </Part>
    </group>
  );
}
