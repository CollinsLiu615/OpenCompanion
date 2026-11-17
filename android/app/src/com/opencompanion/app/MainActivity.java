package com.opencompanion.app;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * OpenCompanion 安卓端。
 *
 * 设计：完全离线，不依赖任何服务器。
 * 界面是本地 assets 里的 HTML，AI 请求由原生 Java 直接发出去
 * （WebView 直连外部接口会遇到 CORS 与被墙的 SSL 问题，交给原生更稳）。
 * 配置与对话都存在 SharedPreferences 里，卸载才会丢。
 */
public class MainActivity extends Activity {

    private WebView web;
    private static final int FILE_CHOOSER = 1001;
    private ValueCallback<Uri[]> pendingCallback;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        web = new WebView(this);
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);          // 本地存储
        s.setAllowFileAccess(true);
        s.setAllowContentAccess(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setTextZoom(100);

        web.setWebViewClient(new WebViewClient());
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb,
                                             FileChooserParams params) {
                pendingCallback = cb;
                Intent i = new Intent(Intent.ACTION_GET_CONTENT);
                i.addCategory(Intent.CATEGORY_OPENABLE);
                i.setType("image/*");
                try {
                    startActivityForResult(Intent.createChooser(i, "选择头像"), FILE_CHOOSER);
                } catch (Exception e) {
                    pendingCallback = null;
                    return false;
                }
                return true;
            }
        });

        web.addJavascriptInterface(new Bridge(), "Native");
        web.loadUrl("file:///android_asset/index.html");

        // 恢复上次保存的定时问候闹钟（App 重启后仍然有效）
        try {
            SharedPreferences sp = prefs();
            AlarmReceiver.rescheduleAll(this, sp.getString("alarms", "[]"));
        } catch (Exception ignored) { }
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        if (req == FILE_CHOOSER && pendingCallback != null) {
            Uri[] out = null;
            if (res == RESULT_OK && data != null) {
                Uri u = data.getData();
                if (u != null) out = new Uri[]{u};
            }
            pendingCallback.onReceiveValue(out);
            pendingCallback = null;
            return;
        }
        super.onActivityResult(req, res, data);
    }

    @Override
    public void onBackPressed() {
        web.evaluateJavascript("window.OCBack&&window.OCBack()",
                new ValueCallback<String>() {
                    @Override
                    public void onReceiveValue(String v) {
                        if (!"true".equals(v)) {
                            MainActivity.super.onBackPressed();
                        }
                    }
                });
    }

    /** 暴露给网页的桥：存配置、发 AI 请求、读头像。 */
    private class Bridge {

        @JavascriptInterface
        public String getConfig() {
            return prefs().getString("config", "{}");
        }

        @JavascriptInterface
        public void saveConfig(String json) {
            prefs().edit().putString("config", json).apply();
        }

        @JavascriptInterface
        public String getPersonas() {
            return prefs().getString("personas", "[]");
        }

        @JavascriptInterface
        public void savePersonas(String json) {
            prefs().edit().putString("personas", json).apply();
        }

        /**
         * 同步 POST 到任意 OpenAI 兼容接口。
         * 在主线程调用会触发 NetworkOnMainThread，因此由网页用 async 包装。
         * 这里用 HttpURLConnection，避免引入 okhttp 依赖。
         */
        /**
         * 异步 POST 到任意 OpenAI 兼容接口。
         *
         * 不能同步返回：网络请求在主线程会抛 NetworkOnMainThreadException。
         * 所以另起线程，完成后用 evaluateJavascript 把结果回调给网页的
         * window.__ocChatDone(callId, resultJson)。
         */
        @JavascriptInterface
        public void chat(final String callId, final String baseUrl, final String apiKey,
                         final String model, final String messagesJson,
                         final double temperature, final int maxTokens) {
            new Thread(new Runnable() {
                @Override
                public void run() {
                    String payload = doChat(baseUrl, apiKey, model, messagesJson, temperature, maxTokens);
                    final String js = "window.__ocChatDone(" + JSONObject.quote(callId) + ","
                            + JSONObject.quote(payload) + ")";
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            web.evaluateJavascript(js, null);
                        }
                    });
                }
            }).start();
        }

        private String doChat(String baseUrl, String apiKey, String model,
                              String messagesJson, double temperature, int maxTokens) {
            JSONObject result = new JSONObject();
            HttpURLConnection conn = null;
            try {
                String base = baseUrl.trim();
                while (base.endsWith("/")) base = base.substring(0, base.length() - 1);
                if (!base.endsWith("/chat/completions")) {
                    base = base + "/chat/completions";
                }
                URL url = new URL(base);
                conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setRequestProperty("Content-Type", "application/json");
                conn.setRequestProperty("Authorization", "Bearer " + apiKey.trim());
                conn.setConnectTimeout(20000);
                conn.setReadTimeout(120000);
                conn.setDoOutput(true);

                JSONObject body = new JSONObject();
                body.put("model", model.trim());
                body.put("messages", new org.json.JSONArray(messagesJson));
                body.put("temperature", temperature);
                body.put("max_tokens", maxTokens);

                try (OutputStream os = conn.getOutputStream()) {
                    os.write(body.toString().getBytes(StandardCharsets.UTF_8));
                }

                int code = conn.getResponseCode();
                InputStream is = (code >= 200 && code < 300)
                        ? conn.getInputStream() : conn.getErrorStream();
                String raw = readAll(is);

                if (code >= 200 && code < 300) {
                    JSONObject obj = new JSONObject(raw);
                    String text = obj.getJSONArray("choices")
                            .getJSONObject(0).getJSONObject("message")
                            .optString("content", "");
                    result.put("ok", true);
                    result.put("text", text.trim());
                } else {
                    result.put("ok", false);
                    result.put("error", friendly(code, raw));
                }
            } catch (Exception e) {
                try {
                    result.put("ok", false);
                    result.put("error", describe(e));
                } catch (Exception ignored) { }
            } finally {
                if (conn != null) conn.disconnect();
            }
            return result.toString();
        }

        @JavascriptInterface
        public void requestPermissions() {
            runOnUiThread(new Runnable() {
                @Override
                public void run() { requestAppPermissions(); }
            });
        }

        /** 网页增删改定时问候后调用，同步给 AlarmManager。 */
        @JavascriptInterface
        public void scheduleAlarms(String json) {
            prefs().edit().putString("alarms", json).apply();
            AlarmReceiver.rescheduleAll(MainActivity.this, json);
        }

        @JavascriptInterface
        public String getAgreed() {
            return prefs().getBoolean("agreed", false) ? "1" : "0";
        }

        @JavascriptInterface
        public void setAgreed(String v) {
            prefs().edit().putBoolean("agreed", "1".equals(v)).apply();
        }

        /** "不同意，退出"：直接结束进程，不给留在后台的机会。 */
        @JavascriptInterface
        public void quit() {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    finishAffinity();
                    android.os.Process.killProcess(android.os.Process.myPid());
                }
            });
        }

        @JavascriptInterface
        public void toast(String msg) {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    Toast.makeText(MainActivity.this, msg, Toast.LENGTH_SHORT).show();
                }
            });
        }
    }

    // ══════ 权限申请 ══════
    private static final int REQ_PERMS = 2001;

    /** 申请通知 + 相册权限。由网页在需要时调用。 */
    private void requestAppPermissions() {
        List<String> need = new ArrayList<>();

        if (Build.VERSION.SDK_INT >= 33) {   // Android 13+
            if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED) {
                need.add(Manifest.permission.POST_NOTIFICATIONS);
            }
            if (checkSelfPermission(Manifest.permission.READ_MEDIA_IMAGES)
                    != PackageManager.PERMISSION_GRANTED) {
                need.add(Manifest.permission.READ_MEDIA_IMAGES);
            }
        } else {
            if (checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE)
                    != PackageManager.PERMISSION_GRANTED) {
                need.add(Manifest.permission.READ_EXTERNAL_STORAGE);
            }
        }

        if (!need.isEmpty()) {
            requestPermissions(need.toArray(new String[0]), REQ_PERMS);
        }
        // 顺带申请「精确闹钟」与「忽略电池优化」，这两个要去系统设置页
        requestExactAlarmAndBattery();
    }

    /** 精确闹钟（Android 12+）需要单独授权，否则定时可能不准。 */
    private void requestExactAlarmAndBattery() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                android.app.AlarmManager am =
                        (android.app.AlarmManager) getSystemService(ALARM_SERVICE);
                if (am != null && !am.canScheduleExactAlarms()) {
                    Intent i = new Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM);
                    i.setData(Uri.parse("package:" + getPackageName()));
                    startActivity(i);
                }
            }
        } catch (Exception ignored) { }

        try {
            // 忽略电池优化：不做的话系统会在息屏后杀掉后台，问候就发不出来
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                android.os.PowerManager pm =
                        (android.os.PowerManager) getSystemService(POWER_SERVICE);
                if (pm != null && !pm.isIgnoringBatteryOptimizations(getPackageName())) {
                    Intent i = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
                    i.setData(Uri.parse("package:" + getPackageName()));
                    startActivity(i);
                }
            }
        } catch (Exception ignored) { }
    }

    @Override
    public void onRequestPermissionsResult(int req, String[] perms, int[] results) {
        super.onRequestPermissionsResult(req, perms, results);
        if (req == REQ_PERMS) {
            int ok = 0;
            for (int r : results) if (r == PackageManager.PERMISSION_GRANTED) ok++;
            Toast.makeText(this, "已获得 " + ok + "/" + perms.length + " 项权限",
                    Toast.LENGTH_SHORT).show();
        }
    }

    private SharedPreferences prefs() {
        return getSharedPreferences("opencompanion", Context.MODE_PRIVATE);
    }

    private static String readAll(InputStream is) throws Exception {
        if (is == null) return "";
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = is.read(buf)) > 0) bos.write(buf, 0, n);
        return bos.toString("UTF-8");
    }

    /** 把 HTTP 码翻译成人话，非技术用户才看得懂。 */
    private static String friendly(int code, String raw) {
        switch (code) {
            case 401: return "API Key 不对（401）。检查是否复制完整、有没有多余空格。";
            case 403: return "没有权限（403）。这个 Key 可能没开通该模型。";
            case 404: return "地址或模型名不对（404）。确认 base_url 是否以 /v1 结尾。";
            case 429: return "请求太频繁或额度用完了（429）。稍后再试或检查余额。";
            case 500:
            case 502:
            case 503: return "服务端出错（" + code + "）。稍后再试。";
            default:  return "请求失败（" + code + "）：" + (raw == null ? "" : raw.substring(0, Math.min(200, raw.length())));
        }
    }

    private static String describe(Exception e) {
        String m = String.valueOf(e.getMessage());
        String n = e.getClass().getSimpleName();
        if (m.contains("Unable to resolve host") || m.contains("UnknownHost")) {
            return "连不上这个地址。检查网络和 base_url 是否写错。";
        }
        if (m.contains("SSL") || m.contains("Cert")) {
            return "HTTPS 证书有问题。确认地址是 https:// 开头。";
        }
        if (n.contains("Timeout")) {
            return "请求超时。网络慢，或该接口响应太慢，稍后再试。";
        }
        if (m.contains("NetworkOnMainThread")) {
            return "调用方式有误（主线程网络请求）。这是 App 的 bug，请反馈。";
        }
        return n + ": " + m;
    }
}
