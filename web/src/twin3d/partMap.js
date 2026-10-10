// Part ids shared with app/twin_view.py (UI_DESIGN §6.2). Single source of truth for the
// frontend: which meshes belong to a part, its label, and where the camera looks from.

export const PART_MAP = {
  // prefixes: mesh-name prefixes in transformer_parts.glb (windings and core are built in code)
  // view: direction from the model towards the camera when the part is focused
  // noData: shown when Python marks the part unavailable for this dataset
  windings:    { label: 'Windings',    prefixes: ['winding'],     view: [-0.15, 0.35, 1.0],
                 noData: 'current not in this dataset' },
  tank:        { label: 'Tank',        prefixes: ['tank'],        view: [0.95, 0.35, 0.8],
                 noData: 'oil temperature not in this dataset' },
  radiators:   { label: 'Radiators',   prefixes: ['radiator'],    view: [1.0, 0.25, 0.55],
                 noData: 'cooling check needs measured oil temperature' },
  conservator: { label: 'Conservator', prefixes: ['conservator'], view: [0.5, 0.45, 1.0],
                 noData: 'oil level not in this dataset' },
  bushings:    { label: 'Bushings',    prefixes: ['bushing'],     view: [-0.2, 0.75, 1.0],
                 noData: 'voltage not in this dataset' },
  core:        { label: 'Core',        prefixes: ['core'],        view: [-0.15, 0.35, 1.0] },
};

export const PART_IDS = Object.keys(PART_MAP);

// The core has no sensor: always neutral, never a health colour (UI_DESIGN §6.2).
export const UNMONITORED = { core: 'not monitored (no sensor)' };

export const STATUS_WORD = { green: 'Normal', yellow: 'Warning', red: 'Critical', grey: 'No data' };
export const ESTIMATED_NOTE = 'Estimated (meter-only)';
export const SENSOR_NOTE = 'Sensor alert: check the device, not the transformer';

export function partOfMesh(name) {
  const lower = (name || '').toLowerCase();
  return PART_IDS.find((id) => PART_MAP[id].prefixes.some((p) => lower.startsWith(p))) ?? null;
}
