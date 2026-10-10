package com.dgt.txalerts;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/** Settings, alert history and snoozes, kept in SharedPreferences. Entries are {a, ds, test, acked}. */
final class Store {
    static volatile String status = "Not monitoring";
    static volatile String health = "";
    static volatile Runnable onChange;
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final int MAX = 200;

    static SharedPreferences sp(Context c) { return c.getApplicationContext().getSharedPreferences("tx", 0); }
    static String get(Context c, String k, String d) { return sp(c).getString(k, d); }
    static void put(Context c, String k, String v) { sp(c).edit().putString(k, v).apply(); }

    static String backend(Context c) { return get(c, "backend", "http://100.73.168.98:8000").replaceAll("/+$", ""); }

    static void changed() { Runnable r = onChange; if (r != null) MAIN.post(r); }

    static synchronized List<JSONObject> alerts(Context c) {
        List<JSONObject> out = new ArrayList<>();
        try {
            JSONArray arr = new JSONArray(get(c, "alerts", "[]"));
            for (int i = 0; i < arr.length(); i++) out.add(arr.getJSONObject(i));
        } catch (Exception ignored) { }
        return out;
    }

    private static void save(Context c, List<JSONObject> list) {
        put(c, "alerts", new JSONArray(list).toString());
    }

    /** Adds the alert unless its id was already seen. Returns the new entry, or null for a duplicate. */
    static synchronized JSONObject add(Context c, JSONObject a, String ds, boolean test) {
        List<JSONObject> list = alerts(c);
        String id = a.optString("id");
        for (JSONObject e : list) if (id.equals(e.optJSONObject("a").optString("id"))) return null;
        try {
            JSONObject entry = new JSONObject().put("a", a).put("ds", ds).put("test", test).put("acked", false);
            list.add(0, entry);
            while (list.size() > MAX) list.remove(list.size() - 1);
            save(c, list);
            changed();
            return entry;
        } catch (Exception e) { return null; }
    }

    static synchronized JSONObject find(Context c, String id) {
        for (JSONObject e : alerts(c)) if (id.equals(e.optJSONObject("a").optString("id"))) return e;
        return null;
    }

    static synchronized void ack(Context c, String id) {
        List<JSONObject> list = alerts(c);
        for (JSONObject e : list) {
            if (id.equals(e.optJSONObject("a").optString("id"))) {
                try { e.put("acked", true); } catch (Exception ignored) { }
            }
        }
        save(c, list);
        changed();
    }

    static synchronized void clear(Context c) { save(c, new ArrayList<>()); changed(); }

    static void snooze(Context c, String type, long ms) { put(c, "snooze_" + type, String.valueOf(System.currentTimeMillis() + ms)); }

    static boolean snoozed(Context c, String type) {
        try { return Long.parseLong(get(c, "snooze_" + type, "0")) > System.currentTimeMillis(); } catch (Exception e) { return false; }
    }
}
