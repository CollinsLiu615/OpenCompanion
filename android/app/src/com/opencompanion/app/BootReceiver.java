package com.opencompanion.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;

/**
 * 开机后重新排一遍闹钟。
 *
 * 手机重启会清空所有 AlarmManager 注册的闹钟，不重建的话
 * 用户设的定时问候会全部失效，而且不会报错——很难发现。
 */
public class BootReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context ctx, Intent intent) {
        if (intent == null) return;
        String action = intent.getAction();
        if (!Intent.ACTION_BOOT_COMPLETED.equals(action)) return;

        SharedPreferences sp = ctx.getSharedPreferences("opencompanion", Context.MODE_PRIVATE);
        String json = sp.getString("alarms", "[]");
        AlarmReceiver.rescheduleAll(ctx, json);
    }
}
