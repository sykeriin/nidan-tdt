package com.dgt.txalerts;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;

/** Pre-written responses (assets/responses.json, shared with the web companion). */
final class Content {
    private static JSONObject root;

    static synchronized void load(Context c) {
        if (root != null) return;
        try (InputStream in = c.getAssets().open("responses.json")) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            root = new JSONObject(out.toString("UTF-8"));
        } catch (Exception e) {
            throw new RuntimeException("cannot load responses.json", e);
        }
    }

    static JSONObject types() { return root.optJSONObject("types"); }

    static JSONObject resp(String type) {
        JSONObject r = types().optJSONObject(type);
        if (r != null) return r;
        try {
            return new JSONObject()
                .put("title", type).put("push", "An alert was raised. Open for details.")
                .put("meaning", "No pre-written response exists for this alert type.")
                .put("safe_to_wait", "Unknown. Ask an engineer.")
                .put("do_now", new JSONArray().put("Contact an engineer")).put("check", new JSONArray())
                .put("escalate_if", "Always.").put("who", "Engineer")
                .put("urgency", new JSONObject().put("critical", "24h").put("warning", "7d").put("info", "7d"));
        } catch (Exception e) { throw new RuntimeException(e); }
    }

    static String sevLabel(String sev) { return root.optJSONObject("severity_label").optString(sev, sev); }

    static String urgencyLabel(JSONObject r, String sev) {
        JSONObject u = r.optJSONObject("urgency");
        String k = u.optString(sev, u.optString("warning", "7d"));
        return root.optJSONObject("urgency_label").optString(k, k);
    }

    static String action(String key) { return root.optJSONObject("actions").optString(key); }
}
