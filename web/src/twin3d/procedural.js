// A cutaway oil-filled power transformer, built in code: pale painted tank with an open window onto the active part
// (copper coils on a three-limb core, lead bundles, tap-changer drum), black ribbed bushings on turrets, a conservator on
// angled supports, radiator panels, and cooling fans.
//
// Mesh names start with the part they belong to (winding, core, tank, radiator, conservator, bushing) because the rest of the
// 3D component finds parts by that prefix. One mesh per object (not one per part) so leader lines and badges can anchor to
// the bushing or radiator that is actually involved. Units are metres-ish; the scene frames the model itself.
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

const PAINT = 0xa6bfb0;       // pale sage green, the usual transformer enamel
const PAINT_DARK = 0x6f8678;
const PORCELAIN = 0x14181d;
const COPPER = 0xd9953a;
const BRASS = 0xc99a3b;
const STEEL = 0x1d232a;
const SILVER = 0xb9c0c6;

function materials() {
  const std = (color, rough, metal = 0) => new THREE.MeshStandardMaterial({ color, roughness: rough, metalness: metal });
  return {
    paint: std(PAINT, 0.62, 0.12),
    paintDark: std(PAINT_DARK, 0.8, 0.05),
    porcelain: std(PORCELAIN, 0.22, 0.05),
    brass: std(BRASS, 0.35, 0.75),
    steel: std(STEEL, 0.55, 0.45),
    silver: std(SILVER, 0.4, 0.7),
    window: std(0xdfe6ea, 0.4, 0.1),
    red: std(0xc23b2e, 0.5, 0.2),
    bolt: std(0x7b868d, 0.45, 0.6),
    rail: std(0x858b91, 0.7, 0.3),
    clamp: std(0xc08038, 0.5, 0.35),
    block: std(0xd9b27a, 0.8, 0),
    coilRing: std(0x8a5a2b, 0.55, 0.3),
  };
}

function coilTexture() {
  const c = document.createElement('canvas');
  c.width = 16;
  c.height = 128;
  const g = c.getContext('2d');
  g.fillStyle = '#e0a043';
  g.fillRect(0, 0, 16, 128);
  g.fillStyle = '#b9772a';
  for (let y = 0; y < 128; y += 8) g.fillRect(0, y, 16, 2);
  g.fillStyle = 'rgba(255,255,255,0.12)';
  for (let y = 3; y < 128; y += 8) g.fillRect(0, y, 16, 1);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(2, 6);
  return t;
}

// ---------- geometry helpers: every helper returns a positioned BufferGeometry ready to merge ----------
const place = (g, x, y, z, rx = 0, ry = 0, rz = 0) => {
  const m = new THREE.Matrix4().compose(new THREE.Vector3(x, y, z), new THREE.Quaternion().setFromEuler(new THREE.Euler(rx, ry, rz)), new THREE.Vector3(1, 1, 1));
  g.applyMatrix4(m);
  return g;
};
const box = (w, h, d, x, y, z, rx, ry, rz) => place(new THREE.BoxGeometry(w, h, d), x, y, z, rx, ry, rz);
// axis: 'y' (default), 'x' or 'z'
const cyl = (rt, rb, h, x, y, z, axis = 'y', seg = 28) => {
  const g = new THREE.CylinderGeometry(rt, rb, h, seg);
  return place(g, x, y, z, axis === 'z' ? Math.PI / 2 : 0, 0, axis === 'x' ? Math.PI / 2 : 0);
};
const ring = (R, r, x, y, z, axis = 'y', seg = 36) => {
  const g = new THREE.TorusGeometry(R, r, 8, seg);                 // lies in the XY plane, axis along z
  return place(g, x, y, z, axis === 'y' ? Math.PI / 2 : 0, axis === 'x' ? Math.PI / 2 : 0, 0);
};
const tube = (points, radius, seg = 24) => new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points.map((p) => new THREE.Vector3(...p))), seg, radius, 6, false);

function mesh(name, geoms, material) {
  const list = geoms.filter(Boolean);
  const geometry = list.length === 1 ? list[0] : mergeGeometries(list, false);
  const m = new THREE.Mesh(geometry, material);
  m.name = name;
  return m;
}

/** Bolt heads along a straight run: a row of small cylinders. */
function bolts(x0, y0, z0, x1, y1, z1, step, r = 0.022, axis = 'z') {
  const n = Math.max(2, Math.round(Math.hypot(x1 - x0, y1 - y0, z1 - z0) / step));
  return Array.from({ length: n + 1 }, (_, i) => {
    const t = i / n;
    return cyl(r, r, 0.03, x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, z0 + (z1 - z0) * t, axis, 10);
  });
}

function bushingProfile(height, trunk = 0.07, shed = 0.125) {
  const pts = [new THREE.Vector2(0, 0), new THREE.Vector2(trunk + 0.03, 0), new THREE.Vector2(trunk, 0.02)];
  const step = 0.082;
  let y = 0.04;
  while (y + step < height) {
    pts.push(new THREE.Vector2(trunk, y), new THREE.Vector2(shed, y + 0.018), new THREE.Vector2(shed + 0.005, y + 0.03), new THREE.Vector2(trunk + 0.012, y + 0.06));
    y += step;
  }
  pts.push(new THREE.Vector2(trunk, height - 0.02), new THREE.Vector2(trunk - 0.01, height), new THREE.Vector2(0, height));
  return pts;
}

export function buildProceduralTransformer() {
  const M = materials();
  const root = new THREE.Group();
  const add = (m) => { root.add(m); return m; };

  // ================= tank, with a cutaway window onto the active part =================
  const X0 = -1.3, X1 = 1.3, Z0 = -0.85, Z1 = 0.85, Y0 = 0.38, Y1 = 2.26;
  const H = Y1 - Y0, yc = (Y0 + Y1) / 2;
  add(mesh('tank_walls', [
    box(X1 - X0, H, 0.06, 0, yc, Z0),                         // back wall
    box(0.06, H, Z1 - Z0, X0, yc, 0),                         // left end
    box(0.06, H, Z1 - Z0, X1, yc, 0),                         // right end (radiators hang here)
    box(0.9, H, 0.06, 0.85, yc, Z1),                          // the part of the front wall that is not cut away
    box(X1 - X0, 0.08, Z1 - Z0, 0, Y0, 0),                    // floor
    ...Array.from({ length: 6 }, (_, i) => box(0.05, H - 0.1, 0.05, X0 + 0.45 + i * 0.4, yc, Z0 - 0.04)),   // stiffeners on the back
  ], M.paint));
  add(mesh('tank_inner', [box(X1 - X0 - 0.1, H - 0.14, 0.02, 0, yc, Z0 + 0.05), box(0.02, H - 0.14, Z1 - Z0 - 0.1, X0 + 0.05, yc, 0)], M.paintDark));
  add(mesh('tank_cover', [
    box(X1 - X0 + 0.14, 0.07, Z1 - Z0 + 0.14, 0, Y1 + 0.035, 0),
    box(0.5, 0.05, 0.3, -0.5, Y1 + 0.095, 0.55), box(0.4, 0.05, 0.3, 0.3, Y1 + 0.095, 0.62),         // access plates
  ], M.paint));
  add(mesh('tank_rim_frame', [                                  // flanged frame around the cutaway
    box(1.78, 0.1, 0.13, -0.41, Y1 - 0.05, Z1 + 0.01), box(1.78, 0.1, 0.13, -0.41, Y0 + 0.14, Z1 + 0.01),
    box(0.1, H - 0.1, 0.13, X0, yc, Z1 + 0.01), box(0.1, H - 0.1, 0.13, 0.43, yc, Z1 + 0.01),
  ], M.paint));
  add(mesh('tank_bolts', [
    ...bolts(-1.28, Y1 - 0.05, Z1 + 0.08, 0.38, Y1 - 0.05, Z1 + 0.08, 0.12), ...bolts(-1.28, Y0 + 0.14, Z1 + 0.08, 0.38, Y0 + 0.14, Z1 + 0.08, 0.12),
    ...bolts(0.43, Y0 + 0.3, Z1 + 0.08, 0.43, Y1 - 0.2, Z1 + 0.08, 0.14), ...bolts(-1.3, Y0 + 0.3, Z1 + 0.08, -1.3, Y1 - 0.2, Z1 + 0.08, 0.14),
    ...bolts(-1.3, Y1 + 0.075, Z1 + 0.05, 1.3, Y1 + 0.075, Z1 + 0.05, 0.16), ...bolts(-1.3, Y1 + 0.075, Z0 - 0.05, 1.3, Y1 + 0.075, Z0 - 0.05, 0.16),
  ], M.bolt));
  // skid, rails and wheels
  add(mesh('tank_skid', [
    box(3.0, 0.14, 0.18, 0, 0.24, 0.55), box(3.0, 0.14, 0.18, 0, 0.24, -0.55),
    box(0.16, 0.12, 1.4, -1.2, 0.26, 0), box(0.16, 0.12, 1.4, 1.2, 0.26, 0), box(0.16, 0.12, 1.4, 0, 0.26, 0),
  ], M.paint));
  add(mesh('tank_rails', [box(3.7, 0.05, 0.14, 0.2, 0.025, 0.55), box(3.7, 0.05, 0.14, 0.2, 0.025, -0.55)], M.rail));
  add(mesh('tank_wheels', [-1.05, 1.05].flatMap((x) => [0.55, -0.55].map((z) => cyl(0.1, 0.1, 0.09, x, 0.12, z, 'z', 20))), M.steel));
  // marshalling box, drain pipe and valve, vertical duct
  add(mesh('tank_control_box', [box(0.56, 0.86, 0.3, -1.05, 1.0, 1.08), box(0.47, 0.76, 0.02, -1.05, 1.0, 1.24)], M.paint));
  add(mesh('tank_control_door', [box(0.1, 0.16, 0.02, -0.9, 1.15, 1.255)], M.window));
  add(mesh('tank_drain', [cyl(0.04, 0.04, 0.55, -1.3, 0.62, 0.95), cyl(0.04, 0.04, 0.3, -1.3, 0.35, 0.8, 'z')], M.silver));
  add(mesh('tank_valve', [cyl(0.05, 0.05, 0.03, -1.3, 0.4, 0.95, 'x', 16), box(0.01, 0.01, 0.11, -1.3, 0.4, 0.95)], M.red));
  add(mesh('tank_duct', [cyl(0.055, 0.055, 1.85, -1.27, 1.3, 0.88)], M.silver));

  // ================= active part (always visible through the window) =================
  const xs = [-0.62, 0, 0.62];
  add(mesh('core_limbs', [...xs.map((x) => box(0.22, 1.5, 0.24, x, 1.28, 0)), box(1.78, 0.18, 0.32, 0, 0.5, 0), box(1.78, 0.18, 0.32, 0, 2.06, 0)], M.steel));
  add(mesh('core_clamps', [box(1.82, 0.05, 0.4, 0, 0.45, 0), box(1.82, 0.05, 0.4, 0, 2.12, 0), box(0.05, 1.7, 0.05, -0.93, 1.28, 0.2), box(0.05, 1.7, 0.05, 0.93, 1.28, 0.2)], M.clamp));
  const tex = coilTexture();
  const coilMat = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.42, metalness: 0.5, color: 0xffffff });
  ['r', 'y', 'b'].forEach((ph, i) => {
    const x = xs[i];
    add(mesh(`winding_${ph}`, [cyl(0.34, 0.34, 1.12, x, 1.3, 0, 'y', 56)], coilMat));
    add(mesh(`winding_rings_${ph}`, [cyl(0.365, 0.365, 0.055, x, 1.89, 0, 'y', 40), cyl(0.365, 0.365, 0.055, x, 0.71, 0, 'y', 40), cyl(0.1, 0.1, 0.2, x, 2.0, 0, 'y', 20)], M.coilRing));
    add(mesh(`winding_blocks_${ph}`, Array.from({ length: 14 }, (_, k) => {
      const a = (k / 14) * Math.PI * 2;
      return box(0.055, 1.06, 0.05, x + Math.cos(a) * 0.35, 1.3, Math.sin(a) * 0.35, 0, -a, 0);
    }), M.block));
  });
  // lead bundles sweeping from the coils to the tap-changer on the left, and risers up to the bushings
  const leads = [];
  xs.forEach((x, i) => {
    for (let k = 0; k < 4; k++) {
      const y = 1.05 + k * 0.12 + i * 0.02;
      leads.push(tube([[x + 0.27, y, 0.12], [x - 0.1, y - 0.03 + (k % 2) * 0.02, 0.36], [-0.55, y + 0.02, 0.4], [-0.86, 1.1 + k * 0.1, 0.3]], 0.024));
    }
  });
  add(mesh('winding_leads', leads, new THREE.MeshStandardMaterial({ color: 0xe3a757, roughness: 0.4, metalness: 0.55 })));
  const hvX = [-0.55, 0.15, 0.85];
  add(mesh('winding_risers', xs.flatMap((x, i) => [
    tube([[x, 1.85, 0.0], [x, 2.1, -0.08], [hvX[i], 2.2, -0.15]], 0.03),
    tube([[x + 0.1, 1.85, 0.12], [x + 0.1, 2.05, 0.3], [hvX[i], 2.2, 0.45]], 0.024),
  ]), new THREE.MeshStandardMaterial({ color: 0xdfa04d, roughness: 0.4, metalness: 0.55 })));
  add(mesh('winding_tapchanger', [
    cyl(0.23, 0.23, 0.55, -0.95, 1.8, 0.26, 'y', 40), ring(0.245, 0.03, -0.95, 1.65, 0.26, 'y'), ring(0.245, 0.03, -0.95, 1.95, 0.26, 'y'),
    cyl(0.05, 0.05, 0.9, -0.95, 1.1, 0.26), cyl(0.12, 0.12, 0.06, -0.95, 2.1, 0.26),
  ], new THREE.MeshStandardMaterial({ color: COPPER, roughness: 0.38, metalness: 0.65 })));

  // ================= bushings on turrets =================
  const hv = hvX.map((x) => ({ x, z: -0.15, h: 0.95, n: `hv_${hvX.indexOf(x) + 1}` }));
  const lv = hvX.map((x, i) => ({ x: x - 0.12, z: 0.45, h: 0.5, n: `lv_${i + 1}` }));
  [...hv, ...lv].forEach(({ x, z, h, n }) => {
    const big = h > 0.8;
    const base = Y1 + 0.07;
    const tr = big ? 0.19 : 0.15, th = big ? 0.4 : 0.3;
    add(mesh(`bushing_turret_${n}`, [cyl(tr, tr, th, x, base + th / 2, z), cyl(tr + 0.035, tr + 0.035, 0.035, x, base + 0.02, z), cyl(tr + 0.03, tr + 0.03, 0.03, x, base + th, z)], M.paint));
    add(mesh(`bushing_window_${n}`, [cyl(0.045, 0.045, 0.04, x + tr * 0.9, base + th * 0.6, z + tr * 0.4, 'x', 16)], M.window));
    const por = new THREE.LatheGeometry(bushingProfile(h, big ? 0.07 : 0.055, big ? 0.125 : 0.1), 28);
    place(por, x, base + th, z);
    add(mesh(`bushing_porcelain_${n}`, [por], M.porcelain));
    add(mesh(`bushing_cap_${n}`, [cyl(0.05, 0.05, 0.1, x, base + th + h + 0.05, z), box(0.12, 0.2, 0.03, x, base + th + h + 0.2, z)], M.brass));
  });

  // ================= conservator on angled supports, with its pipework =================
  const cy = 3.22, cz = -0.78, cx = 1.0;
  add(mesh('conservator_body', [cyl(0.36, 0.36, 2.1, cx, cy, cz, 'x', 48), ring(0.37, 0.025, cx + 1.0, cy, cz, 'x', 48), ring(0.37, 0.025, cx - 1.0, cy, cz, 'x', 48)], M.paint));
  add(mesh('conservator_caps', [cyl(0.38, 0.38, 0.05, cx + 1.07, cy, cz, 'x', 48), cyl(0.38, 0.38, 0.05, cx - 1.07, cy, cz, 'x', 48), ...bolts(cx + 1.1, cy + 0.3, cz, cx + 1.1, cy - 0.3, cz, 0.12, 0.02, 'x')], M.paint));
  add(mesh('conservator_sight', [cyl(0.1, 0.1, 0.05, cx + 1.12, cy, cz, 'x', 24)], M.window));
  add(mesh('conservator_supports', [
    box(0.16, 1.05, 0.2, cx - 0.62, 2.78, cz, 0, 0, -0.33), box(0.16, 1.05, 0.2, cx + 0.62, 2.78, cz, 0, 0, 0.33),
    box(1.9, 0.09, 0.34, cx, Y1 + 0.11, cz), box(1.4, 0.07, 0.3, cx, cy - 0.38, cz)
  ], M.paint));
  add(mesh('conservator_pipe', [
    cyl(0.055, 0.055, 2.6, 0.1, 2.9, -0.45, 'x', 18),
    ...hvX.map((x) => cyl(0.04, 0.04, 0.55, x, 2.62, -0.45)),
    tube([[1.4, 2.9, -0.45], [1.5, 3.0, -0.6], [1.35, cy - 0.34, cz]], 0.05),
    ...[-0.55, 0.85].flatMap((x) => [ring(0.075, 0.015, x, 2.9, -0.45, 'x', 20)]),
  ], M.paint));

  // ================= radiators on the right end, header pipes, and ONAF fans on the left =================
  const RX = 1.95, yRad = 1.38, hRad = 1.58, wRad = 0.95;
  [0, 1, 2].forEach((i) => {
    const z = 0.52 - i * 0.34, x = RX + i * 0.1;
    add(mesh(`radiator_panel_${i + 1}`, [
      box(wRad, hRad, 0.1, x, yRad, z),
      ...Array.from({ length: 9 }, (_, k) => box(0.05, hRad - 0.14, 0.05, x - wRad / 2 + 0.1 + (k * (wRad - 0.2)) / 8, yRad, z + 0.07)),
      box(wRad - 0.04, 0.05, 0.14, x, yRad, z), box(wRad - 0.04, 0.05, 0.14, x, yRad + hRad / 4, z), box(wRad - 0.04, 0.05, 0.14, x, yRad - hRad / 4, z),
      cyl(0.08, 0.08, wRad, x, yRad + hRad / 2 + 0.03, z, 'x', 20), cyl(0.08, 0.08, wRad, x, yRad - hRad / 2 - 0.03, z, 'x', 20),
    ], M.paint));
  });
  add(mesh('radiator_headers', [
    cyl(0.08, 0.08, 1.2, 1.5, 2.2, 0.02, 'z', 18), cyl(0.08, 0.08, 1.2, 1.5, 0.58, 0.02, 'z', 18),
    cyl(0.07, 0.07, 0.4, 1.45, 2.2, 0.02, 'x', 18), cyl(0.07, 0.07, 0.4, 1.45, 0.58, 0.02, 'x', 18),
    cyl(0.14, 0.14, 0.05, 1.33, 2.2, 0.02, 'x', 24), cyl(0.14, 0.14, 0.05, 1.33, 0.58, 0.02, 'x', 24),
  ], M.paint));
  add(mesh('radiator_cooler_left', [box(0.14, 1.5, 1.05, -1.5, 1.28, 0.02), box(0.1, 0.1, 1.1, -1.5, 2.12, 0.02), box(0.1, 0.1, 1.1, -1.5, 0.45, 0.02)], M.paint));
  [1.78, 0.98].forEach((y, i) => {
    const x = -1.64, z = 0.02;
    add(mesh(`radiator_fan_guard_${i + 1}`, [
      ring(0.33, 0.02, x, y, z, 'x'), ring(0.22, 0.012, x - 0.01, y, z, 'x'), ring(0.11, 0.012, x - 0.02, y, z, 'x'),
      ...Array.from({ length: 10 }, (_, k) => box(0.015, 0.33, 0.012, x - 0.02, y, z, (k / 10) * Math.PI * 2 + Math.PI / 20, 0, 0)).map((g) => g),
    ], M.steel));
    add(mesh(`radiator_fan_blades_${i + 1}`, [
      cyl(0.065, 0.065, 0.06, x, y, z, 'x', 20),
      ...Array.from({ length: 5 }, (_, k) => {
        const a = (k / 5) * Math.PI * 2;
        return box(0.012, 0.2, 0.08, x - 0.01, y + Math.cos(a) * 0.12, z + Math.sin(a) * 0.12, a, 0, 0.3);
      }),
    ], M.silver));
  });

  return root;
}
