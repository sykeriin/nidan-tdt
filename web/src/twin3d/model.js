// Builds the transformer (procedural.js) and groups its meshes into parts by name prefix.

import * as THREE from 'three';
import { buildProceduralTransformer } from './procedural.js';
import { PART_IDS, partOfMesh } from './partMap.js';


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

// Returns { root, parts, source }.  parts[id] = { meshes, materials, anchors, box, centre }.
export async function loadModel() {
  const body = buildProceduralTransformer();
  const source = 'procedural';

  const root = new THREE.Group();
  root.add(body);
  root.updateWorldMatrix(true, true);

  // Stand the model on y = 0 and centre it on the vertical axis.
  const bounds = new THREE.Box3();
  body.traverse((o) => { if (o.isMesh) indexedBox(o, bounds); });
  const centre = bounds.getCenter(new THREE.Vector3());
  body.position.set(-centre.x, -bounds.min.y, -centre.z);
  root.updateWorldMatrix(true, true);

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
