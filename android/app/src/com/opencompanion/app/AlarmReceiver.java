package com.opencompanion.app;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Calendar;
import java.util.List;

/**
 * 定时问候的闹钟接收器。
 *
 * 用 AlarmManager 而不是 App 内的计时器：App 被划掉、进入后台、手机重启后，
 * 闹钟依然会响。这是「后台也能收到问候」的关键。
 */
public class AlarmReceiver extends BroadcastReceiver {

    public static final String CHANNEL_ID = "companion_greeting";
    public static final String EXTRA_PID  = "pid";
    public static final String EXTRA_NAME = "name";
    public static final String EXTRA_TEXT = "text";

    private static final String PREFS = "opencompanion";
    private static final String KEY_ALARMS = "alarms";

    @Override
    public void onReceive(Context ctx, Intent intent) {
        String pid  = intent.getStringExtra(EXTRA_PID);
        String name = intent.getStringExtra(EXTRA_NAME);
        String text = intent.getStringExtra(EXTRA_TEXT);
        if (text == null || text.isEmpty()) return;
        if (name == null || name.isEmpty()) name = "伴侣";

        showNotification(ctx, name, text);

        // 排下明天的同一时刻
        try {
            scheduleNext(ctx, pid, name, text);
        } catch (Exception ignored) { }
    }

    // ── 通知 ────────────────────────────────────────────────
    private void showNotification(Context ctx, String title, String body) {
        NotificationManager nm =
                (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) return;

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(
                    CHANNEL_ID, "定时问候", NotificationManager.IMPORTANCE_HIGH);
            ch.setDescription("伴侣的定时问候");
            ch.enableVibration(true);
            nm.createNotificationChannel(ch);
        }

        Intent open = new Intent(ctx, MainActivity.class);
        open.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        PendingIntent pi = PendingIntent.getActivity(
                ctx, (int) System.currentTimeMillis(), open, flags);

        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            b = new Notification.Builder(ctx, CHANNEL_ID);
        } else {
            b = new Notification.Builder(ctx);
        }

        b.setContentTitle(title)
         .setContentText(body)
         .setStyle(new Notification.BigTextStyle().bigText(body))
         .setSmallIcon(android.R.drawable.ic_dialog_info)
         .setAutoCancel(true)
         .setContentIntent(pi);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            b.setPriority(Notification.PRIORITY_HIGH);
        }

        nm.notify((int) (System.currentTimeMillis() % Integer.MAX_VALUE), b.build());
    }

    // ── 排程 ────────────────────────────────────────────────
    /**
     * 读取网页同步过来的问候列表，为每一条排一个每天重复的精确闹钟。
     * 网页在每次增删改问候时调用 Native.scheduleAlarms(...)。
     */
    public static void rescheduleAll(Context ctx, String json) {
        SharedPreferences sp = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        sp.edit().putString(KEY_ALARMS, json).apply();

        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        if (am == null) return;

        JSONArray arr;
        try {
            arr = new JSONArray(json == null ? "[]" : json);
        } catch (Exception e) {
            return;
        }

        for (int i = 0; i < arr.length(); i++) {
            try {
                JSONObject o = arr.getJSONObject(i);
                String at = o.optString("at", "");
                if (at.length() != 5) continue;
                int hh = Integer.parseInt(at.substring(0, 2));
                int mm = Integer.parseInt(at.substring(3, 5));
                setRepeating(ctx, am, i, hh, mm,
                        o.optString("pid", ""),
                        o.optString("name", "伴侣"),
                        o.optString("text", ""));
            } catch (Exception ignored) { }
        }
    }

    private static PendingIntent makeIntent(Context ctx, int slot, int hh, int mm,
                                            String pid, String name, String text) {
        Intent it = new Intent(ctx, AlarmReceiver.class);
        it.putExtra(EXTRA_PID, pid);
        it.putExtra(EXTRA_NAME, name);
        it.putExtra(EXTRA_TEXT, text);

        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        // 用 slot 保证每条问候有独立的 PendingIntent，不会互相覆盖
        return PendingIntent.getBroadcast(ctx, slot, it, flags);
    }

    private static void setRepeating(Context ctx, AlarmManager am, int slot,
                                     int hh, int mm, String pid, String name, String text) {
        Calendar c = Calendar.getInstance();
        c.set(Calendar.HOUR_OF_DAY, hh);
        c.set(Calendar.MINUTE, mm);
        c.set(Calendar.SECOND, 0);
        c.set(Calendar.MILLISECOND, 0);
        if (c.getTimeInMillis() <= System.currentTimeMillis()) {
            c.add(Calendar.DAY_OF_YEAR, 1);   // 今天已过点，从明天开始
        }

        PendingIntent pi = makeIntent(ctx, slot, hh, mm, pid, name, text);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            // Android 12+：精确闹钟需要授权，没授权就用不精确的
            if (am.canScheduleExactAlarms()) {
                am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, c.getTimeInMillis(), pi);
            } else {
                am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, c.getTimeInMillis(), pi);
            }
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, c.getTimeInMillis(), pi);
        } else {
            am.setExact(AlarmManager.RTC_WAKEUP, c.getTimeInMillis(), pi);
        }
    }

    /** 响过之后排下一天的同一时刻 */
    private static void scheduleNext(Context ctx, String pid, String name, String text) {
        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        if (am == null) return;

        Calendar c = Calendar.getInstance();
        c.add(Calendar.DAY_OF_YEAR, 1);
        int hh = c.get(Calendar.HOUR_OF_DAY);
        // 用「现在」推断不出原始时刻，改从偏好里重建
        SharedPreferences sp = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String json = sp.getString(KEY_ALARMS, "[]");
        rescheduleAll(ctx, json);
    }
}
