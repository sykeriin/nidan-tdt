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

    private static String num(double v) {
        double a = Math.abs(v);
        String t = a >= 100 ? String.valueOf(Math.round(v)) : a >= 10 ? String.format(java.util.Locale.US, "%.1f", v) : String.format(java.util.Locale.US, "%.2f", v);
        return t.contains(".") ? t.replaceAll("0+$", "").replaceAll("[.]$", "") : t;
    }

    /** "Now 88.1 °C · expected below 85 °C": the value that raised the alert and the range it should be in. Empty when the alert has neither. */
    static String range(JSONObject a) {
        JSONObject r = resp(a.optString("type"));
        String unit = r.optString("unit", ""), exp = r.optString("expected", "");
        StringBuilder sb = new StringBuilder();
        if (a.has("value") && !a.isNull("value")) sb.append("Now ").append(num(a.optDouble("value"))).append(unit.isEmpty() ? "" : " " + unit);
        if (!exp.isEmpty()) {
            if (exp.contains("{t}") && (!a.has("threshold") || a.isNull("threshold"))) exp = "";
            else if (a.has("threshold") && !a.isNull("threshold")) exp = exp.replace("{t}", num(a.optDouble("threshold")));
        }
        if (!exp.isEmpty()) sb.append(sb.length() > 0 ? " · expected " : "Expected ").append(exp);
        return sb.toString();
    }

    static String sevLabel(String sev) { return root.optJSONObject("severity_label").optString(sev, sev); }

    static String urgencyLabel(JSONObject r, String sev) {
        JSONObject u = r.optJSONObject("urgency");
        String k = u.optString(sev, u.optString("warning", "7d"));
        return root.optJSONObject("urgency_label").optString(k, k);
    }

    static String action(String key) { return root.optJSONObject("actions").optString(key); }
}
