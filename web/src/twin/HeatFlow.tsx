// Heat-flow arrows on the model: core and windings heat the oil, the radiators give it to the air.
// Arrow width ∝ watts (one scale per run: the rated losses P0 + Pk span the widest arrow). Labels are short
// (name + kW); the full balance with stored heat is the HeatBalance figure in the field corner.
// Values: frames losses_noload_W, losses_load_W, heat_dissipated_W (all est.).
import { useFrame } from "@react-three/fiber";
import { Edges, Html } from "@react-three/drei";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { player } from "../player/player";
import { W, Y0 } from "./Transformer";

const num = (v: unknown) => (typeof v === "number" ? v : null);
export const kW = (w: number | null) => (w === null ? "—" : `${(w / 1000).toFixed(w < 10000 ? 2 : 1)} kW`);
const MAX_W = 0.26; // model units for the rated losses
const Z = 0.5;      // drawn in the open front half, just behind the section plane

/** Unit arrow along +x: length 1, shaft width 1 (scaled per frame). */
function useArrowShape() {
  return useMemo(() => {
    const s = new THREE.Shape();
    s.moveTo(0, -0.5); s.lineTo(0.72, -0.5); s.lineTo(0.72, -0.85); s.lineTo(1, 0);
    s.lineTo(0.72, 0.85); s.lineTo(0.72, 0.5); s.lineTo(0, 0.5); s.closePath();
    return new THREE.ShapeGeometry(s);
  }, []);
}

type ArrowDef = { key: string; from: [number, number]; len: number; angle: number; label: string; field: string;
  side: "left" | "right" | "below" };

const ARROWS: ArrowDef[] = [
  // rising beside the outer limbs: core loss on the left, winding loss on the right; out of the radiators to air
  { key: "core", from: [-0.83, 0.5], len: 0.36, angle: 90, label: "core", field: "losses_noload_W", side: "left" },
  { key: "wind", from: [0.83, 0.5], len: 0.5, angle: 90, label: "windings", field: "losses_load_W", side: "right" },
  { key: "air", from: [W / 2 + 0.44, Y0 + 0.62], len: 0.36, angle: 0, label: "to air", field: "heat_dissipated_W", side: "below" },
];

export function HeatFlow({ ratedW }: { ratedW: number | null }) {
  const geo = useArrowShape();
  const mat = useMemo(() => new THREE.MeshBasicMaterial({ color: "#F2EFE6", transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthTest: false }), []);
  const meshes = useRef<(THREE.Mesh | null)[]>([]);
  const labels = useRef<(HTMLDivElement | null)[]>([]);
  const last = useRef(-2);

  useFrame(() => {
    const i = player.index;
    const scale = ratedW ? MAX_W / ratedW : 0;
    ARROWS.forEach((a, n) => {
      const m = meshes.current[n];
      const w = num(player.value(a.field, i));
      if (m) {
        m.visible = w !== null && scale > 0;
        m.scale.set(a.len, Math.max(0.006, (w ?? 0) * scale), 1);
      }
    });
    if (i === last.current || labels.current.some((el) => !el)) return; // Html mounts late
    last.current = i;
    ARROWS.forEach((a, n) => {
      labels.current[n]!.textContent = `${a.label} ${kW(num(player.value(a.field, i)))}`;
    });
  });

  return (
    <group>
      {ARROWS.map((a, n) => (
        <group key={a.key} position={[a.from[0], a.from[1], Z]} rotation={[0, 0, (a.angle * Math.PI) / 180]}>
          <mesh ref={(el) => { meshes.current[n] = el; }} geometry={geo} material={mat} renderOrder={5}>
            <Edges color="#1B1B18" threshold={1} renderOrder={6} />
          </mesh>
          <Html position={[a.len * 0.5, 0, 0]} style={{ pointerEvents: "none" }} zIndexRange={[4, 0]}>
            <div className={`flow-label flow-${a.side}`} ref={(el) => { labels.current[n] = el; }} />
          </Html>
        </group>
      ))}
    </group>
  );
}
