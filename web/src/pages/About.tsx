import { Card, PageTitle } from '../components/ui'

export default function About() {
  return (
    <>
      <PageTitle title="About" sub="PowerNext-AI 2026 · Track 02 · a digital twin for any distribution transformer" />
      <div className="grid grid--2">
        <Card title="What is the twin?">
          <p>
            A digital twin keeps a physical model running next to the real asset and compares the two. Here the model is the IEC 60076-7 thermal and
            ageing model; the data is whatever the transformer reports. The gap between them (the residual) is the main signal. This follows the
            CIGRE JWG A2/D2.65 description of a twin and its &quot;reality gap&quot;.
          </p>
          <p style={{ marginTop: 8 }}>Physics says what should happen, data says what is happening, and the AI watches the gap.</p>
        </Card>
        <Card title="Architecture">
          <ol>
            <li><strong>Data input:</strong> universal adapter for CSV, Excel, JSON and more, with auto-mapping and a capability matrix.</li>
            <li><strong>Twin engine:</strong> thermal model, ageing, remaining life, physics plausibility check.</li>
            <li><strong>Analytics:</strong> rules with hysteresis, residual drift, sensor-vs-asset, oil, electrical, through-fault, Health Index.</li>
            <li><strong>Dashboard and reports:</strong> this app, talking to a FastAPI server.</li>
          </ol>
        </Card>
        <Card title="Generic by design">
          <p>
            The twin is a physics model driven by nameplate numbers, not fitted to one unit. Enter any rating on the Transformer profile page; whatever the
            nameplate does not say falls back to a standard IEC 60076-7 default and is tagged as an assumption. The demo scenarios can be generated for any
            rating, and the residual baseline is generated per transformer too.
          </p>
        </Card>
        <Card title="Fidelity">
          <p>
            Fidelity is the rolling 24 h RMSE between measured and twin top-oil temperature. A rise means either the transformer changed (for example
            cooling degradation) or the model needs recalibrating, and the dashboard says so.
          </p>
        </Card>
        <Card title="Honesty rules">
          <ul>
            <li>Everything generated is labelled <strong>SIMULATED</strong>.</li>
            <li>Alerts say whether the cause is the asset or a sensor/data fault.</li>
            <li>Nameplate values are tagged Confirmed, Assumed, Estimated or To verify; loss values are placeholders until the real nameplate is read.</li>
            <li>Health Index weights and bands are engineering choices, not a trained model, and have not been validated against field failures.</li>
            <li>Results on generated data are regression tests, not evidence of field performance.</li>
          </ul>
        </Card>
        <Card title="Sources">
          <ul>
            <li>IEC 60076-7 thermal model via Alliander <code>transformer-thermal-model</code> (MPL-2.0)</li>
            <li>CPRI, <em>Power Research</em> 19(1), 2023: overloading, insulation and short circuit as principal failure causes</li>
            <li>Kaggle &quot;Distributed Transformer Monitoring&quot; (sreshta140): a different, unrated transformer</li>
            <li>Open-Meteo (cached ambient and humidity)</li>
          </ul>
        </Card>
        <Card title="Credits">
          <p>The 3D transformer is a generic cutaway built in code for this project, not a model of a specific unit. Icons: Phosphor. Fonts: Barlow and JetBrains Mono.</p>
        </Card>
      </div>
    </>
  )
}
