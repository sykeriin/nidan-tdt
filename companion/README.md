# Companion app (PWA)

Shows a notification when the backend raises an anomaly, with a pre-written response for every alert type. No build step, no dependencies: plain HTML/JS.

## Run

```powershell
# terminal 1: backend
.venv\Scripts\python -m uvicorn server.app:app --port 8000
# terminal 2: the app. Port 5173 is required: the backend's CORS list only allows 3000 and 5173.
python -m http.server 5173 --directory companion
```

Open http://localhost:5173, then **Settings → Allow notifications**, pick a dataset (S2 shows the cooling fault being caught early), **Alerts → Start monitoring**.

## How it works

- Reads `GET /api/datasets/{id}/replay` (NDJSON), one state per line. Each state carries the alerts of the last 24 h, so the app de-duplicates by alert `id` and notifies once per new alert.
- The text for each alert comes from [`content/responses.json`](content/responses.json): title, push text, what it means, can it wait, do-now steps, checks, escalate-if, who, urgency per severity. The alert's own value, threshold and backend explanation are shown under "Technical detail".
- Buttons: Acknowledge, Snooze 1 h (per type), Escalate (copies or shares a ready message for the engineer).
- **All 21 types** tab previews every response and sends a TEST notification, with no backend needed.
- Sensor/data alerts say "check the device, not the transformer"; a setting can mute their push.
- `simulated: true` alerts carry a SIMULATED badge.

## Keeping it in step with the backend

`tests/test_companion_content.py` fails if `ALERT_MODULES` gains or loses a type without `responses.json` being updated.

## Limits (be honest in the demo)

- Notifications arrive only while the app is open (a background tab is fine). Real background push needs a push server (VAPID or Telegram), which is not built.
- On a phone, installing the app and notifications need HTTPS. Plain `http://localhost` works on the same computer only. For a phone demo use a tunnel (for example `cloudflared`) for both the app and the backend, then set the Backend URL in Settings.
- The response text is advisory and has not been reviewed by a transformer expert. It deliberately states no numeric test limits; those must come from the standard or nameplate.
- Replay streams are simulated data played back quickly, not a live transformer.
