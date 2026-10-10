// Renderer, lights, camera, picking, hover highlight, status looks, X-ray and camera moves.
// createScene() runs once per page load; render events from Streamlit never touch the model.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { loadModel } from './model.js';
import { PART_MAP } from './partMap.js';

const CANVAS_COLOR = 0xeef1f5;        // --canvas
const HOVER_TINT = new THREE.Color(0.62, 0.75, 0.95);
const WHITE = new THREE.Color(1, 1, 1);

// Status look: the part's colour is multiplied towards the status colour, and warning and
// critical parts also get an outline. Critical pulses at 1 Hz.
const STATUS_LOOK = {
  green:  { color: new THREE.Color(0x16a34a), tint: 0.3,  outline: 0 },
  yellow: { color: new THREE.Color(0xeab308), tint: 0.6,  outline: 0.028 },
  red:    { color: new THREE.Color(0xdc2626), tint: 0.7,  outline: 0.042 },
  grey:   { color: new THREE.Color(0x94a3b8), tint: 0.75, outline: 0 },
};
const NEUTRAL_PARTS = new Set(['core']);   // not monitored: never a health colour

// Thermal-camera palette (ironbow) for the heat-map view: cold is deep indigo, hot is white-yellow.
const IRONBOW = [[0, '#0b0b2a'], [0.28, '#4b1f8f'], [0.5, '#c1317d'], [0.72, '#ff7a3d'], [0.9, '#ffd23f'], [1, '#fff6d6']]
  .map(([t, c]) => [t, new THREE.Color(c)]);
function ironbow(t, out = new THREE.Color()) {
  const x = Math.min(1, Math.max(0, t));
  for (let i = 1; i < IRONBOW.length; i++) {
    if (x <= IRONBOW[i][0]) {
      const [t0, c0] = IRONBOW[i - 1];
      const [t1, c1] = IRONBOW[i];
      return out.copy(c0).lerp(c1, (x - t0) / (t1 - t0));
    }
  }
  return out.copy(IRONBOW[IRONBOW.length - 1][1]);
}

const DEFAULT_VIEW = new THREE.Vector3(-0.45, 0.42, 1).normalize();
const FIT_MARGIN = 1.25;              // whole model in view with about 10 % to spare on each side
const FOCUS_DISTANCE = 0.75;          // of the fit distance, when a part is focused
const IDLE_RESUME_MS = 10000;
const MOVE_MS = 800;
const XRAY_OPACITY = 0.15;
const CLICK_SLOP_PX = 5;

const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

function groundShadow(radius) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 128;
  const ctx = canvas.getContext('2d');
  const gradient = ctx.createRadialGradient(64, 64, 8, 64, 64, 64);
  gradient.addColorStop(0, 'rgba(255, 255, 255, 0.22)');
  gradient.addColorStop(1, 'rgba(255, 255, 255, 0)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 128, 128);
  const mesh = new THREE.Mesh(
    new THREE.CircleGeometry(radius, 48),
    new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true, depthWrite: false }),
  );
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.y = 0.002;
  return mesh;
}

// Back-face shell pushed out along the normals: draws as an outline around the mesh.
function outlineMaterial(objectThickness) {
  const material = new THREE.MeshBasicMaterial({
    side: THREE.BackSide, transparent: true, toneMapped: false,
  });
  material.onBeforeCompile = (shader) => {
    shader.uniforms.thickness = material.userData.thickness;
    shader.vertexShader = `uniform float thickness;\n${shader.vertexShader}`.replace(
      '#include <begin_vertex>',
      '#include <begin_vertex>\n\ttransformed += normalize( normal ) * thickness;',
    );
  };
  material.userData.thickness = { value: objectThickness };
  return material;
}

// handlers: onHover(partId | null, x, y) in container pixels, onSelect(partId | null),
// onFrame() after each rendered frame
export async function createScene(container, handlers = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(CANVAS_COLOR, 0);      // transparent: the stage draws the dark viewfinder behind the model
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.85;
  container.append(renderer.domElement);

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  pmrem.dispose();
  const key = new THREE.DirectionalLight(0xffffff, 1.4);
  key.position.set(4, 8, 5);
  scene.add(key);

  const model = await loadModel();
  scene.add(model.root);

  const bounds = new THREE.Box3().setFromObject(model.root.getObjectByName('internals') ?? model.root);
  for (const part of Object.values(model.parts)) if (part.meshes.length) bounds.union(part.box);
  const centre = bounds.getCenter(new THREE.Vector3());
  const size = bounds.getSize(new THREE.Vector3());
  const sweepRadius = Math.hypot(size.x, size.z) / 2;   // the model turns about its vertical axis
  scene.add(groundShadow(sweepRadius * 1.6));

  // The points that must stay in view, relative to the centre: the model's outermost vertex
  // in each of 200 directions. Box corners would overstate the tilted bushings and the base.
  const directions = Array.from({ length: 200 }, (_, i) => {
    const y = 1 - (2 * (i + 0.5)) / 200;
    const ring = Math.sqrt(1 - y * y);
    const turn = i * Math.PI * (3 - Math.sqrt(5));
    return new THREE.Vector3(Math.cos(turn) * ring, y, Math.sin(turn) * ring);
  });
  const reach = directions.map(() => -Infinity);
  const extremes = directions.map(() => new THREE.Vector3());
  const vertex = new THREE.Vector3();
  for (const mesh of Object.values(model.parts).flatMap((part) => part.meshes)) {
    const position = mesh.geometry.attributes.position;
    const index = mesh.geometry.index;
    const count = index ? index.count : position.count;
    for (let i = 0; i < count; i++) {
      vertex.fromBufferAttribute(position, index ? index.getX(i) : i).applyMatrix4(mesh.matrixWorld).sub(centre);
      for (let d = 0; d < directions.length; d++) {
        const along = vertex.dot(directions[d]);
        if (along > reach[d]) {
          reach[d] = along;
          extremes[d].copy(vertex);
        }
      }
    }
  }

  // Smallest camera distance at which every extreme point is inside the view, checked at
  // 36 rotation angles from the default elevation. `lift` raises the point the camera looks
  // at. The model is wider than it is tall, so the answer depends on the shape of the view.
  const UP = new THREE.Vector3(0, 1, 0);
  const toCamera = new THREE.Vector3();
  const right = new THREE.Vector3();
  const up = new THREE.Vector3();
  const point = new THREE.Vector3();
  function distanceToFit(tanHorizontal, tanVertical, lift) {
    const elevation = Math.asin(DEFAULT_VIEW.y);
    let needed = 0;
    for (let step = 0; step < 36; step++) {
      const azimuth = (step / 36) * Math.PI * 2;
      toCamera.set(Math.cos(elevation) * Math.sin(azimuth), Math.sin(elevation), Math.cos(elevation) * Math.cos(azimuth));
      right.crossVectors(UP, toCamera).normalize();
      up.crossVectors(toCamera, right);
      for (const extreme of extremes) {
        point.copy(extreme);
        point.y -= lift;
        const depth = point.dot(toCamera);     // how far the point sits towards the camera
        needed = Math.max(needed,
          depth + Math.abs(point.dot(right)) / tanHorizontal,
          depth + Math.abs(point.dot(up)) / tanVertical);
      }
    }
    return needed;
  }

  // Seen from above, the near base of the model sits low in the frame. Looking at a point a
  // little below or above the centre balances top and bottom; this picks the best such point.
  function bestFit(tanHorizontal, tanVertical) {
    let best = { distance: Infinity, lift: 0 };
    for (let i = -8; i <= 8; i++) {
      const lift = (i / 8) * size.y * 0.25;
      const distance = distanceToFit(tanHorizontal, tanVertical, lift);
      if (distance < best.distance) best = { distance, lift };
    }
    return best;
  }

  const camera = new THREE.PerspectiveCamera(35, 1, sweepRadius / 50, sweepRadius * 40);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.enablePan = false;
  controls.maxPolarAngle = Math.PI * 0.49;      // never below the ground
  controls.autoRotateSpeed = 1.0;               // about one turn per minute
  controls.target.copy(centre);
  const home = centre.clone();       // where the default view looks

  let lastInput = -Infinity;     // any pointer activity: pauses auto-rotate
  let lastManual = -Infinity;    // the user zoomed or rotated: a resize must not move the camera
  let move = null;               // camera ease in progress

  // Distance that shows the whole model, at any rotation angle, with a margin.
  let fitDistance = 1;
  function resize() {
    const width = container.clientWidth || 1;
    const height = container.clientHeight || 1;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();

    const vertical = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2);
    const horizontal = vertical * camera.aspect;
    const fit = bestFit(horizontal, vertical);
    fitDistance = fit.distance * FIT_MARGIN;
    home.copy(centre).setY(centre.y + fit.lift);
    controls.minDistance = fitDistance * 0.35;   // cannot zoom inside the tank
    controls.maxDistance = fitDistance * 1.5;    // cannot lose the model

    // Keep the framing through a resize, unless the user set their own view just now.
    if (!move && performance.now() - lastManual > IDLE_RESUME_MS) {
      const offset = camera.position.clone().sub(controls.target);
      controls.target.copy(home);
      if (offset.lengthSq() > 0) camera.position.copy(home).add(offset.setLength(fitDistance));
    }
  }
  resize();
  controls.target.copy(home);
  camera.position.copy(home).addScaledVector(DEFAULT_VIEW, fitDistance);
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(container);
  controls.addEventListener('start', () => { lastManual = performance.now(); });

  // ---- hover, X-ray and status looks ----
  let hovered = null;
  const xray = { on: false, value: 0 };
  const internals = model.root.getObjectByName('internals');
  if (internals) internals.visible = false;

  // One outline shell per mesh, sharing its geometry. Shells are never pickable.
  const statuses = {};
  const outlines = {};
  const scale = new THREE.Vector3();
  for (const [id, part] of Object.entries(model.parts)) {
    if (NEUTRAL_PARTS.has(id) || !part.meshes.length) continue;
    const worldScale = part.meshes[0].getWorldScale(scale).x || 1;
    const material = outlineMaterial(0);
    material.userData.worldScale = worldScale;
    const shells = part.meshes.map((mesh) => {
      const shell = new THREE.Mesh(mesh.geometry, material);
      shell.visible = false;
      mesh.add(shell);
      return shell;
    });
    outlines[id] = { material, shells };
  }

  const tint = new THREE.Color();
  const heat = { on: false, values: {}, min: 30, max: 140 };
  const heatColor = new THREE.Color();
  function applyLook(id, pulse = 1) {
    if (heat.on && !NEUTRAL_PARTS.has(id)) {
      // Heat-map view: colour by estimated temperature instead of health status.
      const value = heat.values[id];
      for (const material of model.parts[id].materials) {
        material.color.copy(material.userData.baseColor);
        if (value == null) material.color.multiply(tint.copy(WHITE).lerp(STATUS_LOOK.grey.color, 0.75));
        else material.color.copy(ironbow((value - heat.min) / (heat.max - heat.min), heatColor)).multiplyScalar(1.45);
        if (id === hovered) material.color.multiply(HOVER_TINT);
      }
      for (const shell of outlines[id]?.shells ?? []) shell.visible = false;
      return;
    }
    const look = NEUTRAL_PARTS.has(id) ? null : STATUS_LOOK[statuses[id]];
    for (const material of model.parts[id].materials) {
      material.color.copy(material.userData.baseColor);
      if (look) material.color.multiply(tint.copy(WHITE).lerp(look.color, look.tint * pulse));
      if (id === hovered) material.color.multiply(HOVER_TINT);
    }
    const outline = outlines[id];
    if (!outline) return;
    // The faded tank would show its own shell from the inside, so X-ray hides it.
    const show = Boolean(look?.outline) && !(id === 'tank' && xray.value > 0.01);
    for (const shell of outline.shells) shell.visible = show;
    if (show) {
      outline.material.color.copy(look.color);
      outline.material.opacity = 0.55 + 0.45 * pulse;
      outline.material.userData.thickness.value = look.outline / outline.material.userData.worldScale;
    }
  }

  // parts: view.parts from Python. Only looks change; geometry is never touched.
  function setStatuses(parts) {
    for (const id of Object.keys(model.parts)) {
      const next = parts?.[id]?.status ?? 'grey';
      if (statuses[id] === next) continue;
      statuses[id] = next;
      applyLook(id);
    }
  }

  function setHover(id) {
    if (id === hovered) return;
    const previous = hovered;
    hovered = id;
    if (previous) applyLook(previous);
    if (id) applyLook(id);
    renderer.domElement.style.cursor = id ? 'pointer' : 'grab';
  }

  function applyXray() {
    const opacity = 1 - (1 - XRAY_OPACITY) * xray.value;
    for (const material of model.parts.tank.materials) {
      const transparent = xray.value > 0.01;
      if (material.transparent !== transparent) material.needsUpdate = true;
      material.transparent = transparent;
      material.opacity = opacity;
      material.depthWrite = !transparent;
    }
    if (internals) internals.visible = xray.value > 0.01;
    applyLook('tank');
  }

  // ---- picking ----
  const raycaster = new THREE.Raycaster();
  const pickable = Object.values(model.parts).flatMap((p) => p.meshes);
  const pointer = { x: 0, y: 0, inside: false, moved: false, downX: 0, downY: 0 };

  function pick() {
    const rect = renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2((pointer.x / rect.width) * 2 - 1, -(pointer.y / rect.height) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    const hits = raycaster.intersectObjects(pickable, false)
      .filter((hit) => xray.on || !PART_MAP[hit.object.userData.part].internal);
    if (!hits.length) return null;
    // Through the faded tank, the windings and core win over the tank wall in front of them.
    const inside = xray.on && hits.find((hit) => PART_MAP[hit.object.userData.part].internal);
    return (inside || hits[0]).object.userData.part;
  }

  // Screen position of a part, for badges and leader lines. A part can be several meshes
  // (two radiator banks, six bushings), so the anchor is the mesh centre nearest the camera.
  // occluded: another part sits between the camera and the anchor.
  const projected = new THREE.Vector3();
  const toAnchor = new THREE.Vector3();
  const sightline = new THREE.Raycaster();
  function project(id) {
    const part = model.parts[id];
    if (!part?.anchors.length) return null;
    let anchor = part.anchors[0];
    for (const candidate of part.anchors) {
      if (candidate.distanceToSquared(camera.position) < anchor.distanceToSquared(camera.position)) anchor = candidate;
    }
    const distance = toAnchor.copy(anchor).sub(camera.position).length();
    sightline.set(camera.position, toAnchor.divideScalar(distance));
    sightline.far = distance * 0.98;
    const occluded = sightline.intersectObjects(pickable, false).some((hit) => {
      const other = hit.object.userData.part;
      if (other === id) return false;
      if (PART_MAP[other].internal) return xray.value > 0.5;       // hidden inside an opaque tank
      return !(other === 'tank' && xray.value > 0.5);              // a faded tank hides nothing
    });
    projected.copy(anchor).project(camera);
    return {
      x: (projected.x * 0.5 + 0.5) * container.clientWidth,
      y: (-projected.y * 0.5 + 0.5) * container.clientHeight,
      behind: projected.z > 1,
      occluded,
    };
  }

  function track(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.x = event.clientX - rect.left;
    pointer.y = event.clientY - rect.top;
    pointer.inside = true;
    pointer.moved = true;
    lastInput = performance.now();
  }

  const canvas = renderer.domElement;
  canvas.style.cursor = 'grab';
  canvas.addEventListener('pointermove', track);
  canvas.addEventListener('pointerleave', () => { pointer.inside = false; pointer.moved = true; });
  canvas.addEventListener('wheel', () => { lastInput = lastManual = performance.now(); }, { passive: true });
  canvas.addEventListener('pointerdown', (event) => {
    track(event);
    pointer.downX = pointer.x;
    pointer.downY = pointer.y;
    move = null;                                // a drag cancels a camera move
  });
  canvas.addEventListener('pointerup', (event) => {
    track(event);
    if (Math.hypot(pointer.x - pointer.downX, pointer.y - pointer.downY) > CLICK_SLOP_PX) return;
    handlers.onSelect?.(pick());
  });

  // ---- camera moves ----
  // Eases the camera to `distance` from `target`, looking from `direction`.
  function easeTo(direction, distance, target) {
    const to = new THREE.Spherical().setFromVector3(direction.clone().setLength(distance));
    const from = new THREE.Spherical().setFromVector3(camera.position.clone().sub(controls.target));
    // Turn the short way round.
    to.theta = from.theta + Math.atan2(Math.sin(to.theta - from.theta), Math.cos(to.theta - from.theta));
    move = { start: performance.now(), from, to, fromTarget: controls.target.clone(), target };
    lastInput = performance.now();
  }

  function focusPart(id) {
    const part = model.parts[id];
    if (!part?.meshes.length) return;
    const direction = new THREE.Vector3(...PART_MAP[id].view).normalize();
    easeTo(direction, fitDistance * FOCUS_DISTANCE, centre.clone().lerp(part.centre, 0.6));
    lastManual = performance.now();             // a chosen view: a resize leaves it alone
  }

  // Back to the default framing of the whole model.
  function resetView() {
    easeTo(DEFAULT_VIEW, fitDistance, home.clone());
    lastManual = -Infinity;
  }

  function stepMove(now) {
    const t = reducedMotion ? 1 : Math.min(1, (now - move.start) / MOVE_MS);
    const k = easeInOut(t);
    const s = new THREE.Spherical(
      THREE.MathUtils.lerp(move.from.radius, move.to.radius, k),
      THREE.MathUtils.lerp(move.from.phi, move.to.phi, k),
      THREE.MathUtils.lerp(move.from.theta, move.to.theta, k),
    );
    controls.target.lerpVectors(move.fromTarget, move.target, k);
    camera.position.copy(controls.target).add(new THREE.Vector3().setFromSpherical(s));
    if (t >= 1) move = null;
  }

  // ---- frame loop ----
  let last = performance.now();
  let raf = 0;
  let disposed = false;
  function frame(now) {
    if (disposed) return;
    raf = requestAnimationFrame(frame);
    const dt = now - last;
    last = now;

    if (pointer.moved) {
      pointer.moved = false;
      setHover(pointer.inside ? pick() : null);
      handlers.onHover?.(hovered, pointer.x, pointer.y);
    }

    const target = xray.on ? 1 : 0;
    if (xray.value !== target) {
      const k = reducedMotion ? 1 : 1 - Math.exp(-dt / 70);
      xray.value += (target - xray.value) * k;
      if (Math.abs(target - xray.value) < 0.005) xray.value = target;
      applyXray();
    }

    if (move) stepMove(now);
    // Idle: slow auto-rotate, paused by any input and resumed after 10 s.
    controls.autoRotate = !reducedMotion && !move && now - lastInput > IDLE_RESUME_MS;
    controls.update();

    // Critical parts pulse at 1 Hz (steady under reduced motion).
    const pulse = reducedMotion ? 1 : 0.72 + 0.28 * Math.sin((now / 1000) * 2 * Math.PI);
    for (const id of Object.keys(statuses)) if (statuses[id] === 'red') applyLook(id, pulse);

    renderer.render(scene, camera);
    handlers.onFrame?.();
  }
  raf = requestAnimationFrame(frame);

  return {
    source: model.source,
    parts: model.parts,
    focusPart,
    resetView,
    setStatuses,
    // values: { partId: temperature °C | null }; the colour scale runs min..max
    setHeat(on, values, min, max) {
      heat.on = Boolean(on);
      heat.values = values ?? {};
      if (Number.isFinite(min)) heat.min = min;
      if (Number.isFinite(max) && max > heat.min) heat.max = max;
      for (const id of Object.keys(model.parts)) applyLook(id);
    },
    project,
    setXray(on) { xray.on = Boolean(on); pointer.moved = true; },
    get xray() { return xray.on; },
    // React unmounts the stage: stop the loop and free the GPU resources.
    dispose() {
      disposed = true;
      cancelAnimationFrame(raf);
      resizeObserver.disconnect();
      controls.dispose();
      const freed = new Set();
      const free = (resource) => { if (resource && !freed.has(resource)) { freed.add(resource); resource.dispose?.(); } };
      scene.traverse((o) => {
        free(o.geometry);
        for (const m of [].concat(o.material ?? [])) {
          for (const value of Object.values(m)) if (value?.isTexture) free(value);
          free(m);
        }
      });
      free(scene.environment);
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    },
  };
}
