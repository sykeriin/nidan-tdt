package com.dgt.txalerts;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.NotificationManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.PowerManager;
import android.provider.Settings;
import android.text.InputType;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.style.StyleSpan;
import android.view.Gravity;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;

public class MainActivity extends Activity {
    private static final int BG = Color.parseColor("#0B1220"), CARD = Color.parseColor("#111A2E"),
        FG = Color.parseColor("#E2E8F0"), MUTED = Color.parseColor("#94A3B8");
    private static final String[] SENSOR_TYPES = {"jump_sensor", "range_sensor", "stuck_sensor", "dead_channel", "drift_sensor", "implausible_sensor"};

    private TextView statusTv, healthTv, permTv;
    private Button toggle;
    private LinearLayout list;
    private EditText backend, dataset, speed;
    private Spinner minsev, testType;
    private CheckBox mute;
    private final List<String> typeKeys = new ArrayList<>();

    private int dp(int v) { return (int) (v * getResources().getDisplayMetrics().density + 0.5f); }

    private TextView text(String s, int sp, int color, boolean bold) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(color);
        if (bold) t.setTypeface(Typeface.DEFAULT_BOLD);
        return t;
    }

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        Content.load(this);
        Notifier.ensureChannels(this);

        ScrollView sv = new ScrollView(this);
        sv.setBackgroundColor(BG);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(16), dp(36), dp(16), dp(32));
        sv.addView(root);

        root.addView(text("Transformer-1 alerts", 22, FG, true));
        statusTv = text("", 14, MUTED, false);
        root.addView(statusTv);
        healthTv = text("", 14, Color.parseColor("#86EFAC"), true);
        root.addView(healthTv);

        LinearLayout row = new LinearLayout(this);
        row.setPadding(0, dp(12), 0, dp(8));
        toggle = new Button(this);
        toggle.setOnClickListener(v -> toggle());
        Button clear = new Button(this);
        clear.setText("Clear");
        clear.setOnClickListener(v -> Store.clear(this));
        row.addView(toggle);
        row.addView(clear);
        root.addView(row);
        Button twin = new Button(this);
        twin.setText("Open twin view (3D model + anomaly injection)");
        twin.setAllCaps(false);
        twin.setOnClickListener(v -> { saveSettings(); startActivity(new Intent(this, TwinActivity.class)); });
        root.addView(twin);

        list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        root.addView(list);

        root.addView(text("Settings", 18, FG, true));
        root.addView(label("Backend URL"));
        backend = edit(Store.backend(this), InputType.TYPE_TEXT_VARIATION_URI);
        root.addView(backend);
        root.addView(label("Dataset (S2 = cooling fault, S4a = oil leak, S4b = oil theft, S5 = through faults)"));
        dataset = edit(Store.get(this, "dataset", "S2"), InputType.TYPE_CLASS_TEXT);
        root.addView(dataset);
        root.addView(label("Replay speed (data seconds per real second)"));
        speed = edit(Store.get(this, "speed", "100000"), InputType.TYPE_CLASS_NUMBER);
        root.addView(speed);
        root.addView(label("Notify for"));
        minsev = new Spinner(this);
        minsev.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item,
            new String[]{"All alerts", "Warning and critical", "Critical only"}));
        minsev.setSelection(indexOf(new String[]{"info", "warning", "critical"}, Store.get(this, "minsev", "info")));
        root.addView(minsev);
        mute = new CheckBox(this);
        mute.setText("Sensor / data alerts: list only, no notification");
        mute.setTextColor(FG);
        mute.setChecked("1".equals(Store.get(this, "mutesensor", "0")));
        root.addView(mute);

        root.addView(text("Permissions", 18, FG, true));
        permTv = text("", 13, MUTED, false);
        root.addView(permTv);
        root.addView(button("Allow notifications", v -> askNotifications()));
        root.addView(button("Critical alerts in Do Not Disturb", v ->
            startActivity(new Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS))));
        root.addView(button("Don't restrict battery (keeps monitoring alive)", v -> askBattery()));

        root.addView(text("Test a notification", 18, FG, true));
        testType = new Spinner(this);
        JSONObject types = Content.types();
        List<String> titles = new ArrayList<>();
        for (Iterator<String> it = types.keys(); it.hasNext();) {
            String k = it.next();
            typeKeys.add(k);
            titles.add(types.optJSONObject(k).optString("title") + "  (" + k + ")");
        }
        testType.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, titles));
        root.addView(testType);
        root.addView(button("Send test notification", v -> sendTest()));

        TextView foot = text("Alerts come from the backend's replay of simulated data. The response text is advisory and has not been reviewed by a transformer expert.", 12, MUTED, false);
        foot.setPadding(0, dp(16), 0, 0);
        root.addView(foot);

        setContentView(sv);
        handle(getIntent());
    }

    private TextView label(String s) {
        TextView t = text(s, 13, MUTED, false);
        t.setPadding(0, dp(10), 0, 0);
        return t;
    }

    private EditText edit(String value, int inputType) {
        EditText e = new EditText(this);
        e.setText(value);
        e.setInputType(inputType);
        e.setTextColor(FG);
        e.setSingleLine(true);
        return e;
    }

    private Button button(String s, View.OnClickListener l) {
        Button x = new Button(this);
        x.setText(s);
        x.setAllCaps(false);
        x.setOnClickListener(l);
        return x;
    }

    private static int indexOf(String[] a, String v) {
        for (int i = 0; i < a.length; i++) if (a[i].equals(v)) return i;
        return 0;
    }

    @Override protected void onResume() {
        super.onResume();
        Notifier.ensureChannels(this);
        Store.onChange = this::refresh;
        refresh();
    }

    @Override protected void onPause() {
        saveSettings();
        Store.onChange = null;
        super.onPause();
    }

    @Override protected void onNewIntent(Intent i) { super.onNewIntent(i); setIntent(i); handle(i); }

    private void handle(Intent i) {
        String id = i == null ? null : i.getStringExtra("alert_id");
        if (id != null) { i.removeExtra("alert_id"); showDetail(id); }
    }

    private void saveSettings() {
        Store.put(this, "backend", backend.getText().toString().trim());
        Store.put(this, "dataset", dataset.getText().toString().trim());
        String sp = speed.getText().toString().trim();
        Store.put(this, "speed", sp.isEmpty() ? "100000" : sp);
        Store.put(this, "minsev", new String[]{"info", "warning", "critical"}[minsev.getSelectedItemPosition()]);
        Store.put(this, "mutesensor", mute.isChecked() ? "1" : "0");
    }

    // ------------------------------------------------------------ actions
    private boolean isRunning() { return MonitorService.running; }

    private void toggle() {
        if (isRunning()) {
            startService(new Intent(this, MonitorService.class).setAction(MonitorService.ACTION_STOP));
        } else {
            saveSettings();
            askNotifications();
            startForegroundService(new Intent(this, MonitorService.class));
        }
        toggle.postDelayed(this::refresh, 300);
    }

    private void askNotifications() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
        refresh();
    }

    private void askBattery() {
        PowerManager pm = getSystemService(PowerManager.class);
        if (!pm.isIgnoringBatteryOptimizations(getPackageName()))
            startActivity(new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:" + getPackageName())));
    }

    @Override public void onRequestPermissionsResult(int code, String[] p, int[] r) { refresh(); }

    private void sendTest() {
        saveSettings();
        String type = typeKeys.get(testType.getSelectedItemPosition());
        boolean sensor = false;
        for (String s : SENSOR_TYPES) if (s.equals(type)) sensor = true;
        try {
            JSONObject a = new JSONObject().put("id", "test-" + type + "-" + System.currentTimeMillis())
                .put("timestamp", OffsetDateTime.now().toString()).put("type", type)
                .put("severity", sensor ? "warning" : "critical").put("origin", sensor ? "sensor" : "asset")
                .put("detector", "test").put("explanation", "Test alert from the app. Not from the backend.")
                .put("simulated", false);
            JSONObject entry = Store.add(this, a, "-", true);
            if (entry != null) Notifier.post(this, entry);
        } catch (Exception ignored) { }
    }

    // ------------------------------------------------------------ rendering
    private static String when(String ts) {
        try { return OffsetDateTime.parse(ts).format(DateTimeFormatter.ofPattern("dd MMM, HH:mm")); } catch (Exception e) { return ts; }
    }

    private void refresh() {
        statusTv.setText(isRunning() ? Store.status : ("Not monitoring".equals(Store.status) || Store.status.startsWith("Connect") ? "Not monitoring" : Store.status));
        healthTv.setText(Store.health);
        toggle.setText(isRunning() ? "Stop monitoring" : "Start monitoring");

        boolean notif = getSystemService(NotificationManager.class).areNotificationsEnabled();
        boolean dnd = getSystemService(NotificationManager.class).isNotificationPolicyAccessGranted();
        boolean batt = getSystemService(PowerManager.class).isIgnoringBatteryOptimizations(getPackageName());
        permTv.setText("Notifications: " + (notif ? "allowed" : "NOT allowed") + "\nCritical in Do Not Disturb: " + (dnd ? "allowed" : "not allowed")
            + "\nBattery unrestricted: " + (batt ? "yes" : "no"));

        list.removeAllViews();
        List<JSONObject> entries = Store.alerts(this);
        if (entries.isEmpty()) list.addView(text("No alerts yet.", 14, MUTED, false));
        for (JSONObject e : entries) {
            JSONObject a = e.optJSONObject("a");
            JSONObject r = Content.resp(a.optString("type"));
            String sev = a.optString("severity");
            int color = "critical".equals(sev) ? Color.parseColor("#DC2626") : "warning".equals(sev) ? Color.parseColor("#D97706") : Color.parseColor("#0284C7");
            LinearLayout card = new LinearLayout(this);
            card.setOrientation(LinearLayout.VERTICAL);
            card.setBackgroundColor(CARD);
            card.setPadding(dp(14), dp(10), dp(12), dp(10));
            card.setAlpha(e.optBoolean("acked") ? 0.55f : 1f);
            String tags = Content.sevLabel(sev) + (a.optBoolean("simulated") ? " · SIMULATED" : "") + (e.optBoolean("test") ? " · TEST" : "")
                + ("sensor".equals(a.optString("origin")) ? " · Sensor" : "") + (e.optBoolean("acked") ? " · Acknowledged" : "");
            card.addView(text(tags + "   " + when(a.optString("timestamp")), 12, color, true));
            card.addView(text(r.optString("title"), 16, FG, true));
            card.addView(text(r.optString("push"), 14, MUTED, false));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            lp.setMargins(0, 0, 0, dp(8));
            card.setLayoutParams(lp);
            final String id = a.optString("id");
            card.setOnClickListener(v -> showDetail(id));
            list.addView(card);
        }
    }

    private static void section(SpannableStringBuilder sb, String head, String body) {
        int s = sb.length();
        sb.append(head).append("\n");
        sb.setSpan(new StyleSpan(Typeface.BOLD), s, sb.length() - 1, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        sb.append(body).append("\n\n");
    }

    private static String bullets(JSONArray arr, boolean numbered) {
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < arr.length(); i++) {
            if (i > 0) b.append("\n");
            b.append(numbered ? (i + 1) + ". " : "• ").append(arr.optString(i));
        }
        return b.length() == 0 ? "None." : b.toString();
    }

    private void showDetail(String id) {
        JSONObject e = Store.find(this, id);
        if (e == null) return;
        JSONObject a = e.optJSONObject("a");
        String type = a.optString("type"), sev = a.optString("severity");
        JSONObject r = Content.resp(type);

        SpannableStringBuilder sb = new SpannableStringBuilder();
        sb.append(Content.sevLabel(sev)).append(a.optBoolean("simulated") ? " · SIMULATED" : "").append(e.optBoolean("test") ? " · TEST" : "")
            .append("   ").append(when(a.optString("timestamp"))).append("\n");
        sb.append(Content.urgencyLabel(r, sev)).append(" · ").append(r.optString("who")).append("\n\n");
        if ("sensor".equals(a.optString("origin"))) sb.append("This points to the sensor or data link. Check the device, not the transformer.\n\n");
        section(sb, "What it means", r.optString("meaning"));
        section(sb, "Can it wait?", r.optString("safe_to_wait"));
        section(sb, "Do now", bullets(r.optJSONArray("do_now"), true));
        section(sb, "Check", bullets(r.optJSONArray("check"), false));
        section(sb, "Escalate if", r.optString("escalate_if"));
        StringBuilder tech = new StringBuilder(type + " · " + a.optString("detector"));
        if (!a.isNull("value") && a.has("value")) tech.append(" · value ").append(a.optDouble("value"));
        if (!a.isNull("threshold") && a.has("threshold")) tech.append(" · threshold ").append(a.optDouble("threshold"));
        tech.append("\n").append(a.optString("explanation"));
        section(sb, "Technical detail", tech.toString());

        TextView tv = text("", 15, FG, false);
        tv.setText(sb);
        tv.setPadding(dp(20), dp(12), dp(20), dp(4));
        ScrollView sv = new ScrollView(this);
        sv.addView(tv);

        new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
            .setTitle(r.optString("title")).setView(sv)
            .setPositiveButton(e.optBoolean("acked") ? "Acknowledged" : "Acknowledge", (d, w) -> {
                Store.ack(this, id);
                toast(Content.action("ack_reply"));
            })
            .setNeutralButton("Snooze 1 h", (d, w) -> {
                Store.snooze(this, type, 3600_000L);
                toast(Content.action("snooze_reply"));
            })
            .setNegativeButton("Escalate", (d, w) -> escalate(e, r))
            .show();
    }

    private void toast(String s) { android.widget.Toast.makeText(this, s, android.widget.Toast.LENGTH_LONG).show(); }

    private void escalate(JSONObject e, JSONObject r) {
        JSONObject a = e.optJSONObject("a");
        String vl = "";
        if (a.has("value") && !a.isNull("value")) {
            vl = "Value " + a.optDouble("value") + (a.has("threshold") && !a.isNull("threshold") ? " against threshold " + a.optDouble("threshold") : "") + ". ";
        }
        String msg = Content.action("escalate_template")
            .replace("{title}", r.optString("title")).replace("{severity}", a.optString("severity"))
            .replace("{time}", when(a.optString("timestamp"))).replace("{value_line}", vl)
            .replace("{dataset}", e.optString("ds", "-")).replace("{sim}", a.optBoolean("simulated") ? " (SIMULATED)" : "")
            .replace("{meaning}", r.optString("meaning"));
        Intent send = new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, msg);
        startActivity(Intent.createChooser(send, "Send to engineer"));
    }
}
