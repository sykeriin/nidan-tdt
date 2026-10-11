package com.dgt.txalerts;

import android.app.Notification;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Foreground service: holds the backend's /replay NDJSON stream open and notifies once per new alert. */
public class MonitorService extends Service {
    static final String ACTION_STOP = "stop", ACTION_ACK = "ack";
    private static final int NOTE_ID = 1;
    static volatile boolean running;

    private volatile boolean stop;
    private volatile HttpURLConnection conn;
    private Thread worker;
    private Thread tester;
    private PowerManager.WakeLock wake;

    @Override public IBinder onBind(Intent i) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_ACK.equals(intent.getAction())) {          // "Silence and acknowledge" on the alarm notification
            String id = intent.getStringExtra("alert_id");
            if (id != null) {
                Store.ack(this, id);
                getSystemService(NotificationManager.class).cancel(id.hashCode());
            }
            if (!running) { stopSelf(); return START_NOT_STICKY; }
            return START_STICKY;
        }
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            Store.put(this, "monitoring", "0");
            shutdown("Not monitoring");
            stopForeground(STOP_FOREGROUND_REMOVE);
            stopSelf();
            return START_NOT_STICKY;
        }
        Content.load(this);
        Notifier.ensureChannels(this);
        Notification n = Notifier.monitor(this, "Connecting…");
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTE_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(NOTE_ID, n);
        Store.put(this, "monitoring", "1");
        if (worker == null || !worker.isAlive()) {
            stop = false;
            running = true;
            PowerManager pm = getSystemService(PowerManager.class);
            wake = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "txalerts:monitor");
            wake.acquire();
            worker = new Thread(this::loop, "monitor");
            worker.start();
        }
        if (tester == null || !tester.isAlive()) {
            tester = new Thread(this::pollTests, "tests");
            tester.start();
        }
        return START_STICKY;
    }

    @Override public void onDestroy() { shutdown(null); super.onDestroy(); }

    private void shutdown(String finalStatus) {
        stop = true;
        running = false;
        HttpURLConnection c = conn;
        if (c != null) c.disconnect();
        if (wake != null && wake.isHeld()) wake.release();
        if (finalStatus != null) { Store.status = finalStatus; Store.changed(); }
    }

    private void status(String text) {
        Store.status = text;
        getSystemService(NotificationManager.class).notify(NOTE_ID, Notifier.monitor(this, text));
        Store.changed();
    }

    /** Test alerts sent from the dashboard's Anomaly tests page: GET /api/companion/test-alerts, shown as TEST notifications. */
    private void pollTests() {
        long since = -1;
        while (!stop) {
            try {
                URL url = new URL(Store.resolve(this) + "/api/companion/test-alerts" + (since < 0 ? "" : "?since=" + since));
                HttpURLConnection c = (HttpURLConnection) url.openConnection();
                c.setConnectTimeout(6000);
                c.setReadTimeout(8000);
                if (c.getResponseCode() == 200) {
                    StringBuilder sb = new StringBuilder();
                    try (BufferedReader br = new BufferedReader(new InputStreamReader(c.getInputStream(), StandardCharsets.UTF_8))) {
                        String line;
                        while ((line = br.readLine()) != null) sb.append(line);
                    }
                    JSONObject j = new JSONObject(sb.toString());
                    JSONArray items = j.optJSONArray("items");
                    if (since >= 0 && items != null) {
                        for (int i = 0; i < items.length(); i++) {
                            JSONObject a = items.getJSONObject(i).getJSONObject("alert");
                            boolean live = a.optBoolean("live", false);   // an alert from the live simulated transformer is a real alert for the phone, not a test
                            JSONObject entry = Store.add(this, a, live ? "live" : "-", !live);
                            if (entry != null) Notifier.post(this, entry);
                        }
                    }
                    since = j.optLong("latest", since < 0 ? 0 : since);
                }
                c.disconnect();
            } catch (Exception ignored) { /* backend unreachable: the replay loop reports it; try again shortly */ }
            try { Thread.sleep(2500); } catch (InterruptedException ie) { return; }
        }
    }

    private void loop() {
        while (!stop) {
            try {
                if (stream()) return;
            } catch (Exception e) {
                if (stop) return;
                status("Connection lost, retrying… (" + e.getClass().getSimpleName() + ")");
                try { Thread.sleep(5000); } catch (InterruptedException ie) { return; }
            }
        }
    }

    /**
     * The default source: the simulated live transformer. Its alerts arrive through the alert queue that pollTests() already reads;
     * this loop only keeps the plant awake, shows its health and says whether the server is reachable.
     */
    private boolean watchLive() throws Exception {
        while (!stop) {
            String base = Store.resolve(this);
            try {
                HttpURLConnection c = (HttpURLConnection) new URL(base + "/api/live/state").openConnection();
                conn = c;
                c.setConnectTimeout(6000);
                c.setReadTimeout(8000);
                if (c.getResponseCode() != 200) throw new IOException("HTTP " + c.getResponseCode());
                StringBuilder sb = new StringBuilder();
                try (BufferedReader br = new BufferedReader(new InputStreamReader(c.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = br.readLine()) != null) sb.append(line);
                }
                c.disconnect();
                JSONObject j = new JSONObject(sb.toString());
                JSONObject f = j.optJSONObject("frame");
                if (f != null) Store.health = "Health " + Math.round(f.optDouble("health_score")) + " " + f.optString("health_band");
                JSONArray inj = j.optJSONArray("injections");
                status("Watching the live transformer · " + base.replace("http://", "") + (inj != null && inj.length() > 0 ? " · " + inj.length() + " fault(s) injected" : ""));
            } catch (Exception e) {
                if (stop) return false;
                status("Cannot reach the twin server, retrying… (" + base + ")");
            }
            try { Thread.sleep(4000); } catch (InterruptedException ie) { return false; }
        }
        return false;
    }

    /** Returns true when the replay ended normally. */
    private boolean stream() throws Exception {
        String ds = Store.get(this, "dataset", "live");
        if ("live".equals(ds) || ds.isEmpty()) return watchLive();
        String speed = Store.get(this, "speed", "100000");
        URL url = new URL(Store.resolve(this) + "/api/datasets/" + URLEncoder.encode(ds, "UTF-8") + "/replay?speed=" + speed + "&limit=50000");
        status("Connecting to " + Store.resolve(this) + " …");
        HttpURLConnection c = (HttpURLConnection) url.openConnection();
        conn = c;
        c.setConnectTimeout(8000);
        c.setReadTimeout(120000);
        if (c.getResponseCode() != 200) throw new IOException("HTTP " + c.getResponseCode());
        int n = 0;
        try (BufferedReader br = new BufferedReader(new InputStreamReader(c.getInputStream(), StandardCharsets.UTF_8))) {
            String line;
            while (!stop && (line = br.readLine()) != null) {
                if (line.trim().isEmpty()) continue;
                JSONObject s;
                try { s = new JSONObject(line); } catch (Exception bad) { continue; }
                n++;
                JSONObject h = s.optJSONObject("health");
                if (h != null) Store.health = "Health " + Math.round(h.optDouble("score")) + " " + h.optString("band");
                handleAlerts(s.optJSONArray("alerts"), ds);
                if (n % 25 == 0 || n == 1) status("Monitoring " + ds + " · " + n + " samples");
            }
        } finally { c.disconnect(); }
        if (stop) return false;
        // The replay is over, but the service stays up so test alerts from the dashboard still arrive. Stop ends it.
        status("Replay of " + ds + " finished (" + n + " samples). Listening for test alerts.");
        return true;
    }

    private void handleAlerts(JSONArray arr, String ds) {
        if (arr == null) return;
        List<JSONObject> list = new ArrayList<>();
        for (int i = 0; i < arr.length(); i++) list.add(arr.optJSONObject(i));
        Collections.sort(list, (x, y) -> x.optString("timestamp").compareTo(y.optString("timestamp")));
        for (JSONObject a : list) {
            JSONObject entry = Store.add(this, a, ds, false);
            if (entry != null) Notifier.post(this, entry);
        }
    }
}
