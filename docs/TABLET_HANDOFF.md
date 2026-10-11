# Tablet twin and live anomaly injection: handoff

Everything here is **SIMULATED**. Branch `tablet-v1` (built on `finalv1`). Owner of this part: P3.

## What it is

A live simulation you can attack. A simulated Transformer-1 ("the plant") runs one 15-minute sample at a time. You inject an anomaly (overload, cooling fault, oil leak, a stuck sensor, ...) while it runs. The digital twin and the analytics never see the injection: they only see the resulting measurements, and have to notice. Their alerts appear with the pre-written responses from the companion app.

It is shown two ways:

- **Web page** `/?view=tablet`: 3D twin, injection palette, readings, life clock, alerts. Works in any browser.
- **Android app "TX Alerts"**: the button *Open twin view* opens the same page full-screen in a WebView (immersive, screen kept on).

The PC runs all the model and physics. The tablet is only a display and controls.

```
 tablet (TX Alerts app, WebView)            PC (backend)
 ┌─────────────────────────────┐   http    ┌──────────────────────────────────────────────┐
 │ /?view=tablet               │ ────────▶ │ FastAPI  server/app.py + server/live.py       │
 │  web/src/tablet/Tablet.tsx  │ ◀──────── │   sim/live.py: plant + injections             │
 │  3D scene (existing)        │  NDJSON   │   twin/engine.py: TwinEngine.step()           │
 │  player.append(frame)       │  ticks    │   analytics/pipeline.py: analyze()            │
 └─────────────────────────────┘           └──────────────────────────────────────────────┘
```

## How a tick works (`sim/live.py`)

1. **Plant**: the generator's plant (library with perturbed parameters, sensor noise) advanced one sample with `twin.thermal.Stepper`, the same per-step functions the twin uses. Same plant parameters as the shipped Normal dataset (`data/generated/meta_N.json`).
2. **Injections** change the plant only (load, ambient, cooling, oil level, phase currents, voltage) or the reading only (sensor faults), exactly like `sim/generator.py` does for S1-S5.
3. The measured row goes through `TwinEngine.step()` (nominal parameters) and `analyze()` on a rolling window of the last 672 samples (7 days). About 55 ms per tick.
4. The thermal profile columns (`twin/thermal_profile.py`) and the Health Index are added so the frame has every column the 3D view reads.
5. The tick is `{tick, frame, alerts, injections, events, simulated}`. `alerts` are those raised in the last 24 simulated hours (same rule as `/replay`).

The twin warms up silently for 2 simulated days before the first frame so the detectors have history.

## Files

| Path | What |
|---|---|
| `sim/live.py` | `LiveSession`: plant, injections (`CATALOGUE`), twin + analytics per tick |
| `server/live.py` | FastAPI router `/api/live/*`, included from `server/app.py` |
| `web/src/tablet/Tablet.tsx`, `tablet.css` | the tablet page (portrait and landscape) |
| `web/src/main.tsx` | renders `Tablet` when the URL has `?view=tablet` |
| `web/src/player/player.ts` | `append()` / `clear()` added: the live feed writes into the same player the other views read |
| `companion-android/.../TwinActivity.java` | full-screen WebView; URL is `<Backend URL>/?view=tablet` |
| `companion-android/.../MainActivity.java` | "Open twin view" button + the **Backend URL** setting |
| `companion-android/.../Store.java` | holds the Backend URL (default in `Store.backend()`) |
| `tests/test_live.py`, `tests/test_live_api.py` | 16 plant tests, 5 API tests |

## API (`/api/live`, also in `/docs`)

| Call | Does |
|---|---|
| `GET /catalogue` | the injectable anomalies with their parameters (the UI is built from this) |
| `GET /info` | rated current, thermal constants, asset, speed/pause state |
| `POST /session {seed}` | new session (resets everything); a running stream ends, reconnect it |
| `GET /stream[?limit=N]` | NDJSON, one tick per line, server-paced. A new stream takes over from an old one |
| `POST /inject {kind, params, channel?}` | start an anomaly. Out-of-range values give 400 |
| `POST /clear {id? kind?}` | remove one, a kind, or (empty body) everything |
| `POST /refill` | refill the oil (a leak or theft does not undo itself) |
| `POST /control {rate?, paused?}` | ticks per real second (1-20) and pause |
| `GET /state` | the last tick |

**One global session.** Every connected client shares it. Anomalies stay until cleared, so tap **Clear all** or **Restart** before a demo.

## Anomalies and what they should trigger

Measured on one run (seed 0, after 2.5 simulated days of normal running). 1 tick = 15 simulated minutes. Not a guarantee: they depend on the time of day and the random load.

| Injection | First alerts | After |
|---|---|---|
| Overload 1.2 pu | loading_high, overcurrent, hot_spot_high, ageing_rate_high, top_oil_high | 0.5-3 h |
| Cooling fault (x1.4) | **residual_drift**, then hot_spot_high, ageing_rate_high | 11 h, then 56 h |
| Heatwave +12 °C | none: the twin predicts it | - |
| Phase unbalance | current_unbalance | 1 h |
| Voltage sag / high | voltage_low / voltage_high | 0.8 h |
| Through-fault | through_fault, through_fault_stress | 0.5 h |
| Oil leak (20 % in 1.5 days) | oil_leak, then oil_low | 4.5 h, 20 h |
| Oil theft | oil_low, oil_theft | 0.5 h, 1.5 h |
| Sensor stuck (top oil) | stuck_sensor | 6 h |
| Sensor jump / drift | jump_sensor, residual_drift | 0.2-4 h |
| Sensor dead (top oil, reads 0) | jump_sensor, then stuck_sensor | 0.2 h, 6 h |

The cooling fault is the one where the twin adds lead time over plain thresholds (about 45 h here). Overload, unbalance and theft are caught at the same time by plain thresholds.

## Run it

```powershell
# one-time
py -3.12 -m venv .venv ; .venv\Scripts\python -m pip install -r requirements.txt
cd web ; npm ci ; npm run build ; cd ..          # the backend serves web/dist

# every time: bind to the PC's Tailscale address (see "Changing the IP")
.venv\Scripts\python -m uvicorn server.app:app --host <PC_TAILSCALE_IP> --port 8000
```

Then open `http://<PC_TAILSCALE_IP>:8000/?view=tablet`. After editing the web code run `npm run build` again (the server reads `web/dist` from disk, no restart needed). After editing Python, restart the server.

`python -m server --no-browser --host <PC_TAILSCALE_IP> --port 8000` does the same and also builds `web/` if there is no build yet. Without `--host` it binds `127.0.0.1` only, which a tablet cannot reach.

## Changing the IP between the server and the app

The Tailscale IP of the PC appears in **two** places. The web page itself uses relative URLs, so it needs no change.

| Where | What to change |
|---|---|
| **PC: the server** | restart it with the new address: `uvicorn server.app:app --host <NEW_IP> --port 8000` |
| **Tablet/phone: the app** | open TX Alerts, scroll to **Settings → Backend URL**, enter `http://<NEW_IP>:8000`. It is saved on the device. Tap Start or leave the screen to save |

Steps when the PC's IP changes:

1. On the PC run `tailscale ip -4` to get the new address. (Check it is the PC's Tailscale one, `100.x.x.x`.)
2. Stop the old server and start it with `--host <NEW_IP>`.
3. In the app set **Backend URL** to `http://<NEW_IP>:8000`, then open *Open twin view*.
4. If the twin screen says "Cannot reach the twin": the app shows the URL it tried. Check the server is running, Tailscale is connected on both devices, and the address matches. Tap **Retry**.

Notes:

- **The default in the code** is `Store.backend()` in `companion-android/app/src/main/java/com/dgt/txalerts/Store.java` (`http://100.73.168.98:8000`). The saved Settings value overrides it. Change the default only if you are rebuilding the app anyway (see below), and rebuild + reinstall afterwards.
- **A name instead of an IP stops this problem.** Tailscale MagicDNS gives the PC a stable name like `<pc-name>.<tailnet>.ts.net` (see the Tailscale admin page). Use `http://<pc-name>.<tailnet>.ts.net:8000` as the Backend URL, and bind the server with `--host 0.0.0.0` only if you accept it listening on every interface (it also listens on your LAN and has file-upload endpoints). Binding to the Tailscale IP is the safer default.
- **Over USB instead of Tailscale:** `adb reverse tcp:8000 tcp:8000`, run the server on `127.0.0.1`, and set the Backend URL to `http://localhost:8000`. No IP involved. Re-run `adb reverse` after each reconnect.
- **The web companion** (`companion/`, PWA) defaults to the address it was loaded from, so it follows the server automatically.
- **Windows firewall:** if the tablet times out while the PC itself can open the page, allow inbound TCP 8000 for Python on the Tailscale interface.
- **The phone's TX Alerts monitoring** (notifications) uses the same Backend URL setting.

## Build and install the Android app

Needs JDK 17+, Android SDK platform 36, Gradle 9.5+ (AGP 9.2.1, see `companion-android/README.md`).

```powershell
cd companion-android
gradle assembleDebug
adb install -r app\build\outputs\apk\debug\app-debug.apk
adb shell am start -n com.dgt.txalerts/.TwinActivity      # open the twin screen directly
```

Things that went wrong on this setup:

- **Gradle: "Unable to establish loopback connection"**: the user's `TEMP` path was an 8.3 short name (`SIDDHA~1`). Set `TEMP`, `TMP` and `JAVA_TOOL_OPTIONS=-Djdk.net.unixdomain.tmpdir=C:/tmpj` to a plain folder (create it) before running Gradle.
- **`INSTALL_FAILED_USER_RESTRICTED` on the Xiaomi tablet**: turn on *Developer options → Install via USB* on the tablet. It is separate from USB debugging.
- **Wireless debugging**: the pairing port and the connect port are different numbers. Pair with `adb pair <ip>:<pairing-port> <code>`, then `adb connect <ip>:<connect-port>`.
- **Samsung phone**: critical alerts only break through Do Not Disturb after you grant DND access in the app, and Samsung may kill the monitor unless battery use is set to unrestricted. This affects the notification part, not the twin screen.

## Adding another anomaly

1. Add an entry to `CATALOGUE` in `sim/live.py` (label, group, `oneshot`, parameters with min/max/default). The UI builds itself from it.
2. Apply it in `LiveSession._sample()`. Faults must change the **plant** (or the reading), never a twin or detector input.
3. Add a case to `CASES` in `tests/test_live.py` saying which alert type must appear and within how many ticks.

## Known limits

- **Simulated, not measured.** The plant is the same model family as the twin with perturbed parameters, so detection results say the pipeline works, not that it would on a real transformer.
- **One shared session** (see above). Not a multi-user service.
- **A dead oil-level sensor** (reads 0) is read as oil theft, because the detector cannot tell a zero reading from a real drop.
- **`dead_channel` does not fire** in live injection (it needs a channel that is near zero over the whole window), so a dead temperature sensor shows as `jump_sensor` then `stuck_sensor`.
- **The faults are fast-forwarded** (a cooling fault builds over 36 simulated hours, a leak over 1-5 simulated days). At *Turbo* that is seconds to a minute of real time. This is a demo timescale, not a realistic one.
- **Not run on the full suite**: only `tests/test_live.py` and `tests/test_live_api.py` were run on this branch. Run the whole suite before merging.
- The TX Alerts apps still show the replay-based alerts; the live injection alerts are shown on the twin screen only (they are not pushed as notifications).
- The response text (`companion/content/responses.json`) is advisory and not expert-reviewed.
- Debug-signed APK, sideloaded. No Play Store setup.
