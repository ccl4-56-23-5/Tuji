package app.nefgpstrack;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;

/** Restarts a previously active recording after boot only when the OS allows background location. */
public final class BootReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        if (!Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) return;
        if (!context.getSharedPreferences(TrackService.PREFS, Context.MODE_PRIVATE)
                .getBoolean(TrackService.KEY_ACTIVE, false)) return;
        boolean backgroundAllowed = Build.VERSION.SDK_INT < 29 ||
                context.checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION) ==
                        PackageManager.PERMISSION_GRANTED;
        if (backgroundAllowed) {
            try {
                context.startForegroundService(new Intent(context, TrackService.class)
                        .setAction(TrackService.ACTION_START));
                return;
            } catch (Exception ignored) { /* Let the user restart from the notification. */ }
        }
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        String channel = "resume_tracking";
        manager.createNotificationChannel(new NotificationChannel(
                channel, "轨迹恢复提醒", NotificationManager.IMPORTANCE_DEFAULT));
        PendingIntent open = PendingIntent.getActivity(context, 3,
                new Intent(context, MainActivity.class),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        manager.notify(1002, new Notification.Builder(context, channel)
                .setSmallIcon(R.drawable.ic_stat_location)
                .setContentTitle("请打开NEF轨迹继续记录")
                .setContentText("开机后自动启动被系统限制或缺少后台定位权限")
                .setContentIntent(open)
                .setAutoCancel(true)
                .build());
    }
}
