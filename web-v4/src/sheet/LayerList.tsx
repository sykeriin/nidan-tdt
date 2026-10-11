// The physics layer list, drawn like a CAD drawing's layer table.
import { LAYERS, type LayerId, type Layers } from "../twin/layers";

export function LayerList({ layers, onToggle }: { layers: Layers; onToggle: (id: LayerId) => void }) {
  return (
    <section className="schedule layers" aria-label="Physics layers">
      <header className="schedule-head"><h2>Physics layers</h2><span className="code">Schedule 3</span></header>
      <ul>
        {LAYERS.map((l) => (
          <li key={l.id}>
            <label title={l.physics}>
              <input type="checkbox" checked={layers[l.id]} onChange={() => onToggle(l.id)} />
              <span className="box" aria-hidden="true" />
              <span className="name">{l.label}</span>
            </label>
          </li>
        ))}
      </ul>
    </section>
  );
}
