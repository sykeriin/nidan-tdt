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
    static final String ACTION_STOP = "stop";
    private static final int NOTE_ID = 1;
    static volatile boolean running;

    private volatile boolean stop;
    private volatile HttpURLConnection conn;
    private Thread worker;
    private PowerManager.WakeLock wake;

    @Override public IBinder onBind(Intent i) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
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

    /** Returns true when the replay ended normally. */
    private boolean stream() throws Exception {
        String ds = Store.get(this, "dataset", "S2");
        String speed = Store.get(this, "speed", "100000");
        URL url = new URL(Store.backend(this) + "/api/datasets/" + URLEncoder.encode(ds, "UTF-8") + "/replay?speed=" + speed + "&limit=50000");
        status("Connecting to " + Store.backend(this) + " …");
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
        Store.put(this, "monitoring", "0");
        shutdown("Replay of " + ds + " finished (" + n + " samples)");
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
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
