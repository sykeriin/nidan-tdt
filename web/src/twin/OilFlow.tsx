// ONAN thermosiphon: oil rises through the windings, crosses the top into the radiators, cools as it sinks
// through the fins and returns along the bottom. Instanced particles, positions written in useFrame.
//   speed      ∝ oil_flow_intensity (backend, est.)
//   colour     bottom_oil_C at the bottom, top-oil at the top (heat scale); leaving the radiators the oil has
//              shed radiator_effectiveness of the top→bottom difference (backend, est.), so a weak radiator bank
//              sends warmer oil back.
// The path is drawn geometry; no temperature is computed here.
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { player } from "../player/player";
import { heatColor } from "../data/heat";
import { LIMBS, W, Y0, H } from "./Transformer";
import { thermalValues } from "./Thermal";

const N = 300;
const num = (v: unknown) => (typeof v === "number" ? v : null);

type Seg = { a: THREE.Vector3; b: THREE.Vector3; len: number; kind: "rise" | "top" | "rad" | "bottom" };

function makePath(limbX: number, side: 1 | -1, z: number, finZ: number, jitter: number): { segs: Seg[]; total: number } {
  const xr = side * (W / 2 + 0.26); // radiator plane
  const pts: [THREE.Vector3, Seg["kind"]][] = [
    [new THREE.Vector3(limbX + jitter, 0.47, z), "rise"],
    [new THREE.Vector3(limbX + jitter, Y0 + H - 0.14, z), "top"],
    [new THREE.Vector3(side * (W / 2 - 0.08), Y0 + H - 0.14, z * 0.6), "top"],
    [new THREE.Vector3(xr, Y0 + 1.24, finZ), "rad"],
    [new THREE.Vector3(xr, Y0 + 0.16, finZ), "bottom"],
    [new THREE.Vector3(side * (W / 2 - 0.08), Y0 + 0.1, z * 0.6), "bottom"],
    [new THREE.Vector3(limbX + jitter, Y0 + 0.1, z), "bottom"],
  ];
  const segs: Seg[] = [];
  let total = 0;
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i][0], b = pts[(i + 1) % pts.length][0];
    const len = a.distanceTo(b);
    segs.push({ a, b, len, kind: pts[i][1] });
    total += len;
  }
  return { segs, total };
}

export function OilFlow({ cut, otiSuspect }: { cut: boolean; otiSuspect: boolean }) {
  const mesh = useRef<THREE.InstancedMesh>(null);
  const parts = useMemo(() => {
    const rnd = mulberry(7);
    return Array.from({ length: N }, () => {
      const limb = (["R", "Y", "B"] as const)[Math.floor(rnd() * 3)];
      const side: 1 | -1 = LIMBS[limb] < 0 ? -1 : LIMBS[limb] > 0 ? 1 : rnd() < 0.5 ? -1 : 1;
      // in the open (front) half when sectioned, so the circulation is visible through the cut
      const z = 0.27 + rnd() * 0.16;
      const p = makePath(LIMBS[limb], side, z, -0.42 + Math.floor(rnd() * 8) * 0.12 + 0.02, (rnd() - 0.5) * 0.22);
      return { ...p, u: rnd() };
    });
  }, []);
  const tmp = useMemo(() => ({ o: new THREE.Object3D(), c: new THREE.Color(), top: new THREE.Color(), bot: new THREE.Color(), out: new THREE.Color() }), []);

  useFrame((_, dt) => {
    const m = mesh.current;
    if (!m) return;
    const i = player.index;
    const flow = num(player.value("oil_flow_intensity", i));
    const k = num(player.value("radiator_effectiveness", i));
    const v = thermalValues(i, otiSuspect);
    heatColor(v.oil, tmp.top);
    heatColor(num(player.value("bottom_oil_C", i)), tmp.bot);
    tmp.out.copy(tmp.top).lerp(tmp.bot, Math.min(1, Math.max(0, k ?? 1)));
    // loops per second: a visual rate, proportional to the backend's flow intensity (not to replay speed)
    const step = flow === null ? 0 : (0.02 + 0.09 * flow) * Math.min(dt, 0.05);
    for (let n = 0; n < N; n++) {
      const p = parts[n];
      p.u = (p.u + step) % 1;
      let d = p.u * p.total;
      let s = p.segs[0];
      for (const seg of p.segs) { if (d <= seg.len) { s = seg; break; } d -= seg.len; }
      const f = s.len ? d / s.len : 0;
      tmp.o.position.lerpVectors(s.a, s.b, f);
      tmp.o.updateMatrix();
      m.setMatrixAt(n, tmp.o.matrix);
      // colour: rising oil warms from the returning colour to top-oil; the radiators cool it toward the outlet colour
      if (s.kind === "rise") tmp.c.copy(tmp.out).lerp(tmp.top, f);
      else if (s.kind === "top") tmp.c.copy(tmp.top);
      else if (s.kind === "rad") tmp.c.copy(tmp.top).lerp(tmp.out, f);
      else tmp.c.copy(tmp.out);
      m.setColorAt(n, tmp.c);
    }
    m.instanceMatrix.needsUpdate = true;
    if (m.instanceColor) m.instanceColor.needsUpdate = true;
  });

  return (
    <instancedMesh ref={mesh} args={[undefined, undefined, N]} frustumCulled={false} visible={cut} renderOrder={2}>
      <sphereGeometry args={[0.014, 8, 6]} />
      <meshBasicMaterial toneMapped={false} />
    </instancedMesh>
  );
}

function mulberry(a: number) {
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
