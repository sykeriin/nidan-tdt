# TX Alerts: native Android companion

Standalone Android app (plain Java, no libraries). A foreground service holds the backend's `/replay` NDJSON stream open and posts a real notification for each new alert, with the app closed. Response text is shared with the web companion: `../companion/content/responses.json` is bundled as an asset at build time.

## Notifications

- **Critical**: high-importance channel, alarm-type sound and vibration, set to bypass Do Not Disturb. The bypass works only after you grant DND access (in-app button "Critical alerts in Do Not Disturb").
- **Warning**: default importance. **Info**: low.
- Simple style: title, one-line push text, severity and "simulated data" as sub-text. Tap opens the detail card (what it means, do now, escalate if) with Acknowledge, Snooze 1 h and Escalate (Android share sheet).
- A small ongoing "Watching Transformer-1" notification with a Stop button shows while monitoring.

## Backend address

The phone must reach the backend. Used here: Tailscale (PC `100.73.168.98`). Start the backend bound to that address, not to all interfaces:

```powershell
.venv\Scripts\python -m uvicorn server.app:app --host 100.73.168.98 --port 8000
```

Set the Backend URL in the app's Settings (default `http://100.73.168.98:8000`). Plain http is allowed (`network_security.xml`) because the traffic stays on the private network.

## Build and install

Needs JDK 17+, Android SDK (platform 36), Gradle 9.5+. AGP 9.2.1.

```powershell
cd companion-android
echo "sdk.dir=C\:\\Users\\<you>\\AppData\\Local\\Android\\Sdk" > local.properties
gradle assembleDebug
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

Windows gotcha: if Gradle fails with "Unable to establish loopback connection", your TEMP path is an 8.3 short name (`USERNA~1`). Set `TEMP`, `TMP` and `JAVA_TOOL_OPTIONS=-Djdk.net.unixdomain.tmpdir=C:/tmpj` to a plain folder first.

## Limits

- Debug-signed APK for sideloading. No Play Store setup.
- Delivery depends on the service staying alive. Samsung can kill background apps; use the in-app "Don't restrict battery" button. Not a replacement for FCM push.
- The stream is a replay of simulated data; when it finishes the service stops. There is no live transformer feed.
- Response text is advisory and not expert-reviewed.
