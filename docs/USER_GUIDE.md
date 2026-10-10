# User guide

## Start it

From the repository root:

```powershell
start.bat                      # Windows: creates .venv on first run, serves the dashboard
./start.sh                     # macOS / Linux
```

Open **http://localhost:8000**. Everything runs offline. The built dashboard (`web/dist`) is part of the repository so a laptop without Node can run it; if it is missing, the start script builds it when Node is installed. After editing the frontend run `cd web && npm run build`.

## Take the guided tour

Press **Guided demo** (top right). A narrated tour drives the real app through a healthy month, a cooling fault caught before any temperature alarm,
an overload, an oil leak versus theft, short-circuit stress, the generic transformer profile and the limits. Use Next and Back, pause the auto-advance, or press Esc to leave.

## Read the Overview

- **Status sentence** (top): the transformer's condition in plain words, with the numbers behind it, and the gap between the physics and the sensor.
- **3D transformer:** parts turn yellow or red from the analytics. Hover for status, click for readings, the alert and the recommended test. **Heat map** colours by temperature (measured where there is a sensor, otherwise the twin's estimate; grey means no estimate). **X-ray** shows the windings. A blue "Sensor" badge means the problem is the device, not the transformer.
- **Health:** a 0 to 100 index with six sub-scores. Green is 80 and above, yellow 60 to 79, red below 60. A critical alarm caps it at 40.
- **What the evidence points to:** the likely cause as a share of the evidence, or "nothing stands out". Causes the data cannot observe are listed as such.
- **The gap between physics and data:** the black line is the oil sensor, the grey line is what the physics predicts for the same load and weather, and the hatched band is the gap. When replay is paused, a dashed grey line continues the twin 24 hours ahead with its uncertainty band.
- **Instruments:** hot spot, top oil, load, ageing speed, spare capacity (the largest steady load within limits), and time to a limit.
- **Work order:** priority, schedule and the tests to run. **Remaining insulation life:** a 500-run simulation shown as a fan, with the chance of reaching a temperature limit in 30 days.

## Replay

The dock at the bottom replays the dataset as if it were live. Drag the timeline (the coloured ribbon is the Health Index, the ticks are alerts), or use the buttons: previous alert, back an hour, play, forward an hour, next alert. Pick Slow, Medium or Fast.
Keyboard: **Space** play or pause, **← →** step an hour (Shift: a day), **N** and **P** next and previous alert.

## Use your own transformer

Open **Transformer profile**. Start from an example (Transformer-1, a 1250 kVA unit read from a nameplate photo, or a generic 250, 630 or 1600 kVA), or type a rating and voltage. Add whatever the nameplate says: losses (or the total losses at 100 % and 50 % load),
oil and winding rise, masses, year of manufacture. Anything you leave blank falls back to a standard value, and every value shows where it came from (Confirmed, Calculated, Derived, IEC default, Assumed). A nameplate value always beats a default.

**Simulate** builds a month of load, weather and sensors for that transformer, injects the fault you choose, and runs the whole pipeline. Choose "detailed heat balance" to simulate the transformer with a different physical model from the twin's.

## Load your own data

1. **Import:** drop CSV or Excel files (any sheets). The tool proposes a mapping for each column with a confidence; fix any that are wrong and check the units.
2. Choose **My transformer profile** or **Estimate the rating from the data** (shown with a red banner, since rating-dependent values become assumptions).
3. A file with no time column can be treated as **records** (a ranked per-record view) or given an assumed time step.
4. **Data Health** shows what was read, cleaned, converted and derived, the data-quality flags, and which analyses the data supports and why others are off.

What it needs: a time, a load (phase currents, a mean current, kVA or loading %) and an ambient temperature (filled from cached weather if absent). With only those it runs in **meter-only** mode and estimates temperatures.
An oil temperature, phase currents, phase voltages, an oil level, a neutral current and an event log each switch on more analysis.

## Connect a device

On **Import**, the "Connect a device" card shows how a gateway (an ESP32 or PLC over HTTP, a GPRS modem, a script) posts readings to `POST /api/ingest`. They are mapped and analysed like an upload, and the feed appears in the dataset list as `u-live-<session>`.
The **Stream a 4-day sample** button does exactly that with four days of simulated data, so you can watch a feed arrive without any hardware.

## Other pages

- **Physics:** the IEC equations with this transformer's numbers, the response to a load step (why temperatures lag), what-if replays of a dataset under changed load, ambient and cooling (with the detailed model and harmonics as options), a comparison of the two thermal models with the loss breakdown, and the ageing laws side by side.
- **Loading & Temperatures**, **Failure Modules** (overloading, insulation and short circuit first, as in CPRI's causes of failure), **Alerts & Maintenance** (filter by severity, module, asset or sensor origin; every alert has a recommendation).
- **Real Field Data:** a different, unrated transformer with real measurements, showing how the twin treats sensors it cannot trust.
- **Self-Test:** CPRI's acceptance-sheet format. The 50 A and 60 °C values are bench settings, not operating alarms.
- **Reports:** the report as one self-contained HTML page (use Print to save a PDF), the full time series as CSV, and everything as JSON.

## If something does not work

| Symptom | Fix |
|---|---|
| "Backend offline" banner | Start the server (`start.bat` or `uvicorn server.app:app --port 8000`) and press Retry. |
| Port 8000 busy | Run `uvicorn server.app:app --port 8001` and open that port. |
| Empty dataset list | Run `python -m dt.api rebuild` to build the cached scenarios. |
| 3D view blank | The browser blocked WebGL; the rest of the dashboard works. |
| A page says "Not available: …" | The dataset lacks a channel. The sentence says which. |

Everything generated is labelled **SIMULATED**. Results on generated data are regression evidence, not field performance.
