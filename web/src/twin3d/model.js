// Loads transformer_parts.glb, groups its meshes into parts by name prefix, and builds the
// windings and core inside the tank. Falls back to a primitive model with the same part ids.

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { PART_IDS, partOfMesh } from './partMap.js';

const MODEL_URL = `${import.meta.env.BASE_URL}models/transformer_parts.glb`;

// The split meshes share vertex buffers, so a geometry's own bounding box covers far more
// than the part. This measures only the vertices the mesh actually indexes.
function indexedBox(mesh, box = new THREE.Box3()) {
  const position = mesh.geometry.attributes.position;
  const index = mesh.geometry.index;
  const v = new THREE.Vector3();
  const count = index ? index.count : position.count;
  for (let i = 0; i < count; i++) {
    v.fromBufferAttribute(position, index ? index.getX(i) : i).applyMatrix4(mesh.matrixWorld);
    box.expandByPoint(v);
  }
  return box;
}

function named(name, geometry, material, position) {
  const mesh = new THREE.Mesh(geometry, material);
  mesh.name = name;
  mesh.position.set(...position);
  return mesh;
}

// Simple stand-in used only if the .glb cannot be loaded. Same mesh-name prefixes.
function buildFallback() {
  const group = new THREE.Group();
  const steel = new THREE.MeshStandardMaterial({ color: 0x9aa4ae, metalness: 0.3, roughness: 0.6 });
  const porcelain = new THREE.MeshStandardMaterial({ color: 0x7a5a48, metalness: 0.1, roughness: 0.5 });

  group.add(named('tank', new THREE.BoxGeometry(3.4, 2.2, 1.8), steel, [0.3, 1.3, 0]));
  group.add(named('tank_fitting_1', new THREE.BoxGeometry(3.8, 0.2, 2.2), steel, [0.3, 0.1, 0]));
  let n = 1;
  for (const z of [1.25, -1.25]) {
    for (const x of [-0.7, 0.3, 1.3]) {
      group.add(named(`radiator_${n++}`, new THREE.BoxGeometry(0.85, 1.5, 0.6), steel, [x, 1.35, z]));
    }
  }
  const drum = named('conservator', new THREE.CylinderGeometry(0.38, 0.38, 1.5, 24), steel, [-1.9, 3.1, 0]);
  drum.rotation.x = Math.PI / 2;
  group.add(drum);
  [-0.6, 0.3, 1.2].forEach((x, i) => {
    group.add(named(`bushing_hv_${i + 1}`, new THREE.CylinderGeometry(0.09, 0.15, 1.3, 16), porcelain, [x, 3.05, 0.45]));
    group.add(named(`bushing_lv_${i + 1}`, new THREE.CylinderGeometry(0.07, 0.11, 0.7, 16), porcelain, [x, 2.75, -0.45]));
  });
  return group;
}

function coilTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = 8;
  canvas.height = 64;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#b87333';
  ctx.fillRect(0, 0, 8, 64);
  ctx.fillStyle = '#8a5326';
  for (let y = 0; y < 64; y += 8) ctx.fillRect(0, y, 8, 2);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(1, 5);
  return texture;
}

// Three copper coils (R, Y, B) on a three-limb core, sized to sit inside the tank body.
function buildInternals(tankBox) {
  const size = tankBox.getSize(new THREE.Vector3());
  const centre = tankBox.getCenter(new THREE.Vector3());
  const spacing = size.x * 0.23;
  const radius = Math.min(size.x * 0.095, size.z * 0.3);
  const height = size.y * 0.46;
  const y = tankBox.min.y + size.y * 0.5;

  const copper = new THREE.MeshStandardMaterial({ map: coilTexture(), metalness: 0.55, roughness: 0.4 });
  const iron = new THREE.MeshStandardMaterial({ color: 0x6b7280, metalness: 0.4, roughness: 0.6 });
  const group = new THREE.Group();
  group.name = 'internals';

  ['r', 'y', 'b'].forEach((phase, i) => {
    const x = centre.x + (i - 1) * spacing;
    group.add(named(`winding_${phase}`, new THREE.CylinderGeometry(radius, radius, height, 40), copper, [x, y, centre.z]));
    group.add(named(`core_limb_${phase}`, new THREE.BoxGeometry(radius * 0.9, height * 1.12, radius * 0.9), iron, [x, y, centre.z]));
  });
  const yoke = new THREE.BoxGeometry(spacing * 2 + radius * 1.5, height * 0.16, radius * 0.95);
  group.add(named('core_yoke_top', yoke, iron, [centre.x, y + height * 0.64, centre.z]));
  group.add(named('core_yoke_bottom', yoke, iron, [centre.x, y - height * 0.64, centre.z]));
  return group;
}

// Returns { root, parts, source }.  parts[id] = { meshes, materials, anchors, box, centre }.
export async function loadModel() {
  let body;
  let source = 'glb';
  try {
    body = (await new GLTFLoader().loadAsync(MODEL_URL)).scene;
  } catch (err) {
    console.warn('[twin3d] could not load the .glb, using the primitive model', err);
    body = buildFallback();
    source = 'fallback';
  }

  const root = new THREE.Group();
  root.add(body);
  root.updateWorldMatrix(true, true);

  // Stand the model on y = 0 and centre it on the vertical axis.
  const bounds = new THREE.Box3();
  body.traverse((o) => { if (o.isMesh) indexedBox(o, bounds); });
  const centre = bounds.getCenter(new THREE.Vector3());
  body.position.set(-centre.x, -bounds.min.y, -centre.z);
  root.updateWorldMatrix(true, true);

  let tank = null;
  body.traverse((o) => { if (o.isMesh && o.name === 'tank') tank = o; });
  if (tank) {
    root.add(buildInternals(indexedBox(tank)));
    root.updateWorldMatrix(true, true);
  }

  const parts = Object.fromEntries(PART_IDS.map((id) =>
    [id, { meshes: [], materials: [], anchors: [], box: new THREE.Box3(), centre: new THREE.Vector3() }]));
  const clones = new Map();   // one material per part, so a part can be tinted or faded alone

  root.traverse((o) => {
    if (!o.isMesh) return;
    const id = partOfMesh(o.name);
    if (!id) {
      console.warn(`[twin3d] mesh "${o.name}" matches no part and is not interactive`);
      return;
    }
    const key = `${id}:${o.material.uuid}`;
    if (!clones.has(key)) {
      const material = o.material.clone();
      material.userData.baseColor = material.color.clone();
      clones.set(key, material);
      parts[id].materials.push(material);
    }
    o.material = clones.get(key);
    o.userData.part = id;
    parts[id].meshes.push(o);
    // Each mesh centre is a possible anchor for leader lines and badges.
    const own = indexedBox(o);
    parts[id].anchors.push(own.getCenter(new THREE.Vector3()));
    parts[id].box.union(own);
  });
  for (const part of Object.values(parts)) {
    if (part.meshes.length) part.box.getCenter(part.centre);
  }

  return { root, parts, source };
}
