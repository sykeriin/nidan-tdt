// Every inspectable part: what it is, what it does physically, and which backend fields its callout shows.
// Geometry lives in Transformer.tsx; anchors (model units, metres-ish) are where the leader line starts.
import { f, type FieldRef } from "../data/fields";

export type PartId =
  | "tank" | "oil" | "core" | "winding-R" | "winding-Y" | "winding-B" | "radiators" | "conservator" | "oil-gauge"
  | "breather" | "hv-bushings" | "lv-R" | "lv-Y" | "lv-B" | "lv-N" | "cts" | "oti" | "ambient" | "nameplate";

export interface Part {
  id: PartId;
  name: string;
  role: string;
  anchor: [number, number, number];
  // leader direction on screen: which way the callout box sits, and its offset in px from the anchor
  side: "left" | "right";
  dx: number;
  dy: number;
  fields: FieldRef[];
  note?: string;
}

const topOil = f("row", "OTI_C", "top-oil", "°C", "measured");
const twinOil = f("twin", "twin_oil_C", "top-oil", "°C", "twin");
const residual = f("twin", "residual_oil_C", "measured − twin", "K", "residual");

const winding = (ph: "R" | "Y" | "B", x: number, side: "left" | "right", dy: number): Part => ({
  id: `winding-${ph}` as PartId,
  name: `Winding, phase ${ph}`,
  role: "Copper coils (LV inside, HV outside). Load loss ∝ I² heats them; the hottest point ages the paper.",
  anchor: [x, 1.22, 0.24],
  side, dx: 150, dy,
  fields: [
    f("row", `I${ph}`, "phase current", "A", "measured", { digits: 0 }),
    f("twin", "twin_hs_C", "hot-spot", "°C", "twin"),
    f("row", "WTI_C", "hot-spot", "°C", "measured"),
    f("twin", "aging_rate_actual", "ageing rate", "× normal", "twin", { digits: 2 }),
  ],
});

const lv = (ph: "R" | "Y" | "B", x: number, dy: number): Part => ({
  id: `lv-${ph}` as PartId,
  name: `LV bushing, phase ${ph}`,
  role: "Brings the 415 V phase conductor out through the cover.",
  anchor: [x, 1.95, 0.3],
  side: "right", dx: 130, dy,
  fields: [
    f("row", `V${ph}`, "phase voltage", "V", "measured"),
    f("row", `I${ph}`, "phase current", "A", "measured", { digits: 0 }),
  ],
});

export const PARTS: Part[] = [
  {
    id: "tank", name: "Tank", role: "Steel enclosure that holds the oil; its walls shed part of the heat to the air.",
    anchor: [-0.9, 0.55, 0.35], side: "left", dx: 140, dy: 40, fields: [topOil, twinOil, residual],
  },
  {
    id: "oil", name: "Insulating oil", role: "Insulates, and carries heat from windings to radiators by natural circulation.",
    anchor: [-0.3, 1.45, 0.0], side: "left", dx: 160, dy: -10, fields: [topOil, twinOil, residual],
  },
  {
    id: "core", name: "Core", role: "Laminated steel carrying the magnetic flux; its no-load loss heats the oil constantly.",
    anchor: [-0.55, 0.36, 0.08], side: "left", dx: 150, dy: 70,
    fields: [
      f("asset", "no_load_loss_W", "no-load loss", "W", "info", { digits: 0, estimated: true }),
      f("twin", "load_pu", "load factor K", "pu", "twin", { digits: 2 }),
    ],
  },
  winding("R", -0.55, "left", -60),
  winding("Y", 0, "right", -120),
  winding("B", 0.55, "right", -40),
  {
    id: "radiators", name: "Radiator bank", role: "Thin fins where the oil gives its heat to the air (ONAN: natural oil, natural air).",
    anchor: [1.3, 0.9, 0.3], side: "right", dx: 120, dy: 50,
    fields: [f("row", "amb_C", "ambient air", "°C", "measured"), twinOil],
  },
  {
    id: "conservator", name: "Conservator", role: "Expansion tank: the oil level rises and falls with oil temperature.",
    anchor: [-0.2, 2.2, -0.5], side: "left", dx: 150, dy: -70, fields: [f("row", "OLI_pct", "oil level", "%", "measured")],
  },
  {
    id: "oil-gauge", name: "Oil-level gauge", role: "Glass gauge on the conservator; the sensor behind the oil-level channel.",
    anchor: [0.66, 2.05, -0.5], side: "right", dx: 140, dy: -110, fields: [f("row", "OLI_pct", "oil level", "%", "measured")],
  },
  {
    id: "breather", name: "Silica-gel breather", role: "Dries the air the conservator breathes in as the oil cools and contracts.",
    anchor: [-0.82, 1.62, -0.5], side: "left", dx: 140, dy: -20,
    fields: [f("row", "RH_pct", "air humidity", "%", "measured", { digits: 0 })],
  },
  {
    id: "hv-bushings", name: "HV bushings (11 kV)", role: "Bring the 11 kV supply in through the cover.",
    anchor: [-0.5, 2.15, -0.15], side: "left", dx: 150, dy: -40, fields: [],
    note: "Not measured: the dataset has LV channels only.",
  },
  lv("R", -0.45, -10),
  lv("Y", -0.15, 20),
  lv("B", 0.15, 50),
  {
    id: "lv-N", name: "LV neutral bushing", role: "Return path for unbalanced phase current.",
    anchor: [0.45, 1.85, 0.3], side: "right", dx: 120, dy: 80, fields: [f("row", "IN", "neutral current", "A", "measured")],
  },
  {
    id: "cts", name: "LV current transformers", role: "Rings around the LV leads that measure the phase currents.",
    anchor: [-0.45, 1.62, 0.37], side: "left", dx: 150, dy: 30,
    fields: [
      f("row", "IR", "I R", "A", "measured", { digits: 0 }),
      f("row", "IY", "I Y", "A", "measured", { digits: 0 }),
      f("row", "IB", "I B", "A", "measured", { digits: 0 }),
    ],
  },
  {
    id: "oti", name: "Top-oil temperature pocket", role: "Thermometer well in the hottest oil, under the cover (OTI).",
    anchor: [0.72, 1.62, 0.36], side: "right", dx: 130, dy: -60, fields: [topOil, twinOil, residual],
  },
  {
    id: "ambient", name: "Ambient sensor", role: "Shaded air thermometer beside the transformer (ATI).",
    anchor: [1.75, 1.45, 0.75], side: "right", dx: 110, dy: -30,
    fields: [f("row", "ATI_C", "air temperature", "°C", "measured"), f("row", "amb_C", "ambient used by twin", "°C", "measured")],
  },
  {
    id: "nameplate", name: "Nameplate", role: "Rated values the twin is built on.",
    anchor: [-0.4, 0.62, 0.56], side: "left", dx: 140, dy: 90,
    fields: [
      f("asset", "rating_kVA", "rating", "kVA", "info", { digits: 0 }),
      f("asset", "lv_voltage_V", "LV voltage", "V", "info", { digits: 0 }),
      f("asset", "i_rated_A", "rated current", "A", "info", { digits: 0 }),
      f("asset", "load_loss_W", "load loss", "W", "info", { digits: 0, estimated: true }),
    ],
  },
];

export const PART = Object.fromEntries(PARTS.map((p) => [p.id, p])) as Record<PartId, Part>;
