package com.opencompanion.app;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Calendar;

/**
 * 定时问候的闹钟接收器。
 *
 * 用 AlarmManager 而不是 App 内的计时器：App 被划掉、进入后台、手机重启后，
 * 闹钟依然会响。这是「后台也能收到问候」的关键。
 *
 * 两种内容模式：
 *   1. useAI = true  —— 在后台调用用户配置的 AI，用其角色人设生成内容
 *   2. useAI = false —— 直接弹出用户填写的固定文字（不联网）
 *
 * AI 失败（无网络 / 超时 / 接口报错）时**一律回落到固定文字**，
 * 保证闹钟到点一定会有东西弹出来，不会静默失败。
 */
public class AlarmReceiver extends BroadcastReceiver {

    public static final String CHANNEL_ID = "companion_greeting";
    public static final String EXTRA_PID     = "pid";
    public static final String EXTRA_NAME    = "name";
    public static final String EXTRA_TEXT    = "text";
    public static final String EXTRA_USE_AI  = "useAI";
    // 注意：API Key 与人设**不放进 Intent**。
    // AlarmManager 的 Intent 会由系统保存，理论上可被同签名的其它组件
    // 或设备管理员读取；而且密钥原本已用 Keystore 加密存放在本地，
    // 没必要再复制一份到系统服务里。闹钟触发时按 pid 现场读取即可。
    public static final String EXTRA_MODEL   = "model";

    private static final String PREFS = "opencompanion";
    private static final String KEY_ALARMS = "alarms";

    /** AI 生成的整体超时。闹钟线程不能长时间挂着，超时就回落。 */
    private static final int AI_TIMEOUT_MS = 25000;

    @Override
    public void onReceive(Context ctx, Intent intent) {
        final String pid     = intent.getStringExtra(EXTRA_PID);
        final String name    = safe(intent.getStringExtra(EXTRA_NAME), "伴侣");
        final String text    = safe(intent.getStringExtra(EXTRA_TEXT), "");
        final boolean useAI  = intent.getBooleanExtra(EXTRA_USE_AI, false);

        // 现场从加密存储里取 API 配置与角色人设，避免密钥出现在 Intent 中。
        // 用 final 数组承载，供下面的匿名线程访问：{baseUrl, apiKey, model, persona}
        final String[] ai = new String[]{"", "", "", ""};
        if (useAI) {
            try {
                JSONObject cfg = new JSONObject(SecureStore.get(ctx, "config", "{}"));
                ai[0] = cfg.optString("base_url", "");
                ai[1] = cfg.optString("api_key", "");
                ai[2] = cfg.optString("model", "");

                JSONArray arr = new JSONArray(SecureStore.get(ctx, "personas", "[]"));
                for (int i = 0; i < arr.length(); i++) {
                    JSONObject one = arr.getJSONObject(i);
                    if (pid != null && pid.equals(one.optString("id"))) {
                        ai[3] = one.optString("persona", one.optString("brief", ""));
                        break;
                    }
                }
            } catch (Exception ignored) { }
        }

        if (text.isEmpty()) return;

        final Context appCtx = ctx.getApplicationContext();
        final PendingResult pending = goAsync();

        // 网络请求不能占住 onReceive，用子线程；无论成败最后都 finish
        new Thread(new Runnable() {
            @Override
            public void run() {
                String body = text;   // 兜底：用户原文
                boolean aiOk = false;

                if (useAI && !ai[0].isEmpty() && !ai[1].isEmpty() && !ai[2].isEmpty()) {
                    try {
                        String gen = generateWithAI(ai[0], ai[1], ai[2], name, ai[3], text);
                        if (gen != null && !gen.trim().isEmpty()) {
                            body = gen.trim();
                            aiOk = true;
                        }
                    } catch (Exception ignored) {
                        // 任何异常都不影响弹通知，下面用兜底文本
                    }
                }

                showNotification(appCtx, name, body);
                logResult(appCtx, pid, name, useAI, aiOk, body);

                try { scheduleNext(appCtx); } catch (Exception ignored) { }
                if (pending != null) pending.finish();
            }
        }).start();
    }

    private static String safe(String v, String def) {
        return (v == null || v.isEmpty()) ? def : v;
    }

    // ══════ AI 生成 ══════
    /**
     * 调用 OpenAI 兼容接口生成问候内容。
     * 返回 null 表示失败，调用方会自动回落到固定文本。
     */
    private String generateWithAI(String baseUrl, String apiKey, String model,
                                  String name, String persona, String topic) throws Exception {
        String base = baseUrl.trim();
        while (base.endsWith("/")) base = base.substring(0, base.length() - 1);
        if (!base.endsWith("/chat/completions")) base = base + "/chat/completions";

        String sys = "你正在扮演「" + name + "」。请严格按照以下人设说话：\n\n"
                + (persona.isEmpty() ? "（用户未填写详细人设，请用自然亲切的语气）" : persona)
                + "\n\n只输出一条发给对方的消息本身，不要用列表，不要解释你在做什么，全程中文。";

        String userMsg = "请围绕这个主题主动发一条消息给对方：" + topic.trim();

        JSONObject sysMsg = new JSONObject().put("role", "system").put("content", sys);
        JSONObject userM = new JSONObject().put("role", "user").put("content", userMsg);
        JSONArray msgs = new JSONArray().put(sysMsg).put(userM);

        JSONObject payload = new JSONObject()
                .put("model", model.trim())
                .put("messages", msgs)
                .put("temperature", 0.95)
                .put("max_tokens", 200);

        HttpURLConnection conn = null;
        try {
            URL url = new URL(base);
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setRequestProperty("Authorization", "Bearer " + apiKey.trim());
            conn.setConnectTimeout(AI_TIMEOUT_MS);
            conn.setReadTimeout(AI_TIMEOUT_MS);
            conn.setDoOutput(true);

            try (OutputStream os = conn.getOutputStream()) {
                os.write(payload.toString().getBytes(StandardCharsets.UTF_8));
            }

            int code = conn.getResponseCode();
            if (code < 200 || code >= 300) return null;   // 回落

            String raw = readAll(conn.getInputStream());
            JSONObject obj = new JSONObject(raw);
            return obj.getJSONArray("choices")
                      .getJSONObject(0)
                      .getJSONObject("message")
                      .optString("content", null);
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private static String readAll(InputStream is) throws Exception {
        if (is == null) return "";
        java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        int n;
        while ((n = is.read(buf)) > 0) bos.write(buf, 0, n);
        return bos.toString("UTF-8");
    }

    /** 记录本次是 AI 生成还是回落，方便用户事后核对。 */
    private static void logResult(Context ctx, String pid, String name,
                                  boolean wantAI, boolean aiOk, String body) {
        try {
            String line = new java.text.SimpleDateFormat("yyyy-MM-dd HH:mm:ss",
                    java.util.Locale.getDefault()).format(new java.util.Date())
                    + "\t" + name + "\t"
                    + (wantAI ? (aiOk ? "AI生成" : "AI失败·回落固定文本") : "固定文本")
                    + "\t" + body.replace("\n", " ") + "\n";
            java.io.FileOutputStream fos = ctx.openFileOutput("greetings.log",
                    Context.MODE_APPEND);
            fos.write(line.getBytes(StandardCharsets.UTF_8));
            fos.close();
        } catch (Exception ignored) { }
    }

    // ══════ 通知 ══════
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

    // ══════ 排程 ══════
    public static void rescheduleAll(Context ctx, String json) {
        android.content.SharedPreferences sp =
                ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
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
                setRepeating(ctx, am, i, hh, mm, o);
            } catch (Exception ignored) { }
        }
    }

    private static PendingIntent makeIntent(Context ctx, int slot, JSONObject o) {
        Intent it = new Intent(ctx, AlarmReceiver.class);
        it.putExtra(EXTRA_PID,     o.optString("pid", ""));
        it.putExtra(EXTRA_NAME,    o.optString("name", "伴侣"));
        it.putExtra(EXTRA_TEXT,    o.optString("text", ""));
        it.putExtra(EXTRA_USE_AI,  o.optBoolean("useAI", false));
        // 只带 pid / name / text / useAI，其余敏感数据由 pid 现场查
        

        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        return PendingIntent.getBroadcast(ctx, slot, it, flags);
    }

    private static void setRepeating(Context ctx, AlarmManager am, int slot,
                                     int hh, int mm, JSONObject o) {
        Calendar c = Calendar.getInstance();
        c.set(Calendar.HOUR_OF_DAY, hh);
        c.set(Calendar.MINUTE, mm);
        c.set(Calendar.SECOND, 0);
        c.set(Calendar.MILLISECOND, 0);
        if (c.getTimeInMillis() <= System.currentTimeMillis()) {
            c.add(Calendar.DAY_OF_YEAR, 1);
        }

        PendingIntent pi = makeIntent(ctx, slot, o);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
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

    private static void scheduleNext(Context ctx) {
        android.content.SharedPreferences sp =
                ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        rescheduleAll(ctx, sp.getString(KEY_ALARMS, "[]"));
    }
}
