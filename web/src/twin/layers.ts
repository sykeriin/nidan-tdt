// Physics layers, listed like a drawing's layer list. Each one toggles a group of visuals (see BINDINGS.md).
export type LayerId = "temperature" | "ghost" | "heatflow" | "oilflow" | "thermometer" | "lag" | "lifeclock";

export const LAYERS: { id: LayerId; label: string; physics: string }[] = [
  { id: "temperature", label: "Temperature field", physics: "oil and winding colour on the heat scale" },
  { id: "ghost", label: "Twin ghost", physics: "physics prediction drawn over the measured model" },
  { id: "heatflow", label: "Heat flow", physics: "losses → oil → radiators → air, width ∝ W" },
  { id: "oilflow", label: "Oil circulation", physics: "ONAN thermosiphon, speed ∝ flow" },
  { id: "thermometer", label: "Section thermometer", physics: "bottom oil → top oil → hot-spot" },
  { id: "lag", label: "Thermal lag", physics: "τ oil 180 min, τ winding 4 min" },
  { id: "lifeclock", label: "Life clock", physics: "V = 2^((θh − 98)/6)" },
];

export type Layers = Record<LayerId, boolean>;
export const ALL_ON: Layers = Object.fromEntries(LAYERS.map((l) => [l.id, true])) as Layers;
