package com.dgt.txalerts;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.media.AudioAttributes;
import android.media.RingtoneManager;
import android.net.Uri;

import org.json.JSONObject;

final class Notifier {
    static final String CH_CRIT_DND = "critical_dnd_v1", CH_CRIT_STD = "critical_std_v1", CH_WARN = "warning_v1", CH_INFO = "info_v1", CH_MON = "monitor_v1";

    private static int rank(String sev) { return "critical".equals(sev) ? 2 : "warning".equals(sev) ? 1 : 0; }

    static void ensureChannels(Context c) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        nm.deleteNotificationChannel("critical_v1");
        // Android only honours setBypassDnd when the app already has DND access at creation time, so keep two channels
        // and pick the right one when posting.
        boolean dnd = nm.isNotificationPolicyAccessGranted();
        Uri alarm = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM);
        if (alarm == null) alarm = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION);
        AudioAttributes aa = new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build();
        for (String id : new String[]{CH_CRIT_STD, CH_CRIT_DND}) {
            boolean bypass = CH_CRIT_DND.equals(id);
            if (bypass && !dnd) continue;
            NotificationChannel crit = new NotificationChannel(id, "Critical alerts", NotificationManager.IMPORTANCE_HIGH);
            crit.setDescription("Needs action now. Loud alarm sound and vibration.");
            crit.enableVibration(true);
            crit.setVibrationPattern(new long[]{0, 400, 200, 400, 200, 600});
            crit.setSound(alarm, aa);
            if (bypass) crit.setBypassDnd(true);
            nm.createNotificationChannel(crit);
        }

        NotificationChannel warn = new NotificationChannel(CH_WARN, "Warnings", NotificationManager.IMPORTANCE_DEFAULT);
        warn.setDescription("Needs attention soon.");
        nm.createNotificationChannel(warn);

        nm.createNotificationChannel(new NotificationChannel(CH_INFO, "Info", NotificationManager.IMPORTANCE_LOW));

        NotificationChannel mon = new NotificationChannel(CH_MON, "Monitoring status", NotificationManager.IMPORTANCE_LOW);
        mon.setDescription("The small ongoing notification shown while the app watches the backend.");
        nm.createNotificationChannel(mon);
    }

    static PendingIntent open(Context c, String alertId, int req) {
        Intent i = new Intent(c, MainActivity.class).setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        if (alertId != null) i.putExtra("alert_id", alertId);
        return PendingIntent.getActivity(c, req, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    static Notification monitor(Context c, String text) {
        Intent stop = new Intent(c, MonitorService.class).setAction(MonitorService.ACTION_STOP);
        PendingIntent stopPi = PendingIntent.getService(c, 1, stop, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(c, CH_MON).setSmallIcon(R.drawable.ic_bolt)
            .setContentTitle("Watching Transformer-1").setContentText(text).setOngoing(true).setOnlyAlertOnce(true)
            .setContentIntent(open(c, null, 2))
            .addAction(new Notification.Action.Builder(null, "Stop", stopPi).build()).build();
    }

    /** Raises the notification for a stored entry, unless filtered by the user's settings. */
    static void post(Context c, JSONObject entry) {
        JSONObject a = entry.optJSONObject("a");
        String sev = a.optString("severity", "warning"), type = a.optString("type"), id = a.optString("id");
        boolean test = entry.optBoolean("test");
        if ("sensor".equals(a.optString("origin")) && "1".equals(Store.get(c, "mutesensor", "0"))) return;
        if (rank(sev) < rank(Store.get(c, "minsev", "info"))) return;
        if (!test && Store.snoozed(c, type)) return;

        JSONObject r = Content.resp(type);
        String title = (test ? "TEST · " : "") + r.optString("title");
        String sub = Content.sevLabel(sev) + (a.optBoolean("simulated") ? " · simulated data" : "");
        String channel = "critical".equals(sev) ? (c.getSystemService(NotificationManager.class).isNotificationPolicyAccessGranted() ? CH_CRIT_DND : CH_CRIT_STD) : "warning".equals(sev) ? CH_WARN : CH_INFO;
        int color = "critical".equals(sev) ? Color.parseColor("#DC2626") : "warning".equals(sev) ? Color.parseColor("#D97706") : Color.parseColor("#0284C7");

        String range = Content.range(a);
        String body = r.optString("push") + (range.isEmpty() ? "" : "\n" + range);
        Notification n = new Notification.Builder(c, channel).setSmallIcon(R.drawable.ic_bolt).setColor(color)
            .setContentTitle(title).setContentText(range.isEmpty() ? r.optString("push") : range).setSubText(sub)
            .setStyle(new Notification.BigTextStyle().bigText(body))
            .setAutoCancel(true).setCategory(Notification.CATEGORY_STATUS).setShowWhen(true)
            .setContentIntent(open(c, id, id.hashCode())).build();
        c.getSystemService(NotificationManager.class).notify(id.hashCode(), n);
    }
}
