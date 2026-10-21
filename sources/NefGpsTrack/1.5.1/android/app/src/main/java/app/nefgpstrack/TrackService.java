package app.nefgpstrack;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.location.altitude.AltitudeConverter;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.SystemClock;
import android.os.Bundle;

public final class TrackService extends Service {
    static final String PREFS = "tracking";
    static final String KEY_ACTIVE = "active";
    static final String KEY_MODE = "mode";
    static final String KEY_ERROR = "error";
    static final String KEY_HEARTBEAT = "serviceHeartbeatUtcMs";
    static final String ACTION_START = "app.nefgpstrack.START";
    static final String ACTION_STOP = "app.nefgpstrack.STOP";
    static final String ACTION_SINGLE = "app.nefgpstrack.SINGLE";
    static final String ACTION_CONFIG = "app.nefgpstrack.CONFIG";
    static final String CHANNEL = "tracking_status";
    private static final String ERROR_CHANNEL = "tracking_errors";
    private static final int NOTIFICATION_ID = 1001;
    private static final int ERROR_NOTIFICATION_ID = 1003;

    private LocationManager manager;
    private HandlerThread locationThread;
    private Handler locationHandler;
    private TrackDb database;
    private AltitudeConverter altitudeConverter;
    private volatile boolean foreground;
    private long lastNoticeElapsed;
    static volatile boolean finishing;
    private boolean slowMode;
    private boolean singleMode;
    private final Runnable singleTimeout = () -> { if(singleMode&&!finishing) {getSharedPreferences(PREFS,MODE_PRIVATE).edit().putString(KEY_ERROR,"单点定位超时，未保存位置。请到开阔处重试。").apply();finishRecording();} };
    private void finishRecording(){onStartCommand(new Intent(this,TrackService.class).setAction(ACTION_STOP),0,0);}
    private long lastMovingElapsed;
    private volatile Location lastAccepted;
    private final Runnable idleCheck = () -> {
        if (getSharedPreferences(PREFS, MODE_PRIVATE).getBoolean(KEY_ACTIVE, false) &&
                getSharedPreferences(PREFS, MODE_PRIVATE).getInt(KEY_MODE, 0) == 0 && !slowMode) {
            slowMode = true;
            try { configure(); } catch (Exception ignored) { /* surfaced by missing fixes */ }
        }
    };
    private final Runnable heartbeat = new Runnable() {
        @Override public void run() {
            if (!foreground) return;
            getSharedPreferences(PREFS, MODE_PRIVATE).edit()
                    .putLong(KEY_HEARTBEAT, System.currentTimeMillis()).apply();
            updateNotice(true);
            locationHandler.postDelayed(this, 60000L);
        }
    };

    private final LocationListener listener = new LocationListener() {
        @Override public void onLocationChanged(Location location) { accept(location); }
        @Override public void onProviderEnabled(String provider) {}
        @Override public void onProviderDisabled(String provider) {}
        @Override public void onStatusChanged(String provider, int status, Bundle extras) {}
    };

    @Override public void onCreate() {
        super.onCreate();
        finishing=false;
        manager = (LocationManager) getSystemService(LOCATION_SERVICE);
        database = new TrackDb(this);
        if (Build.VERSION.SDK_INT >= 34) altitudeConverter = new AltitudeConverter();
        locationThread = new HandlerThread("track-location");
        locationThread.start();
        locationHandler = new Handler(locationThread.getLooper());
        NotificationManager notifications = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        notifications.createNotificationChannel(new NotificationChannel(
                CHANNEL, "轨迹记录状态", NotificationManager.IMPORTANCE_LOW));
        notifications.createNotificationChannel(new NotificationChannel(
                ERROR_CHANNEL, "轨迹记录异常", NotificationManager.IMPORTANCE_DEFAULT));
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? ACTION_START : intent.getAction();
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        if (ACTION_STOP.equals(action)) {
            if(finishing)return START_NOT_STICKY;
            finishing=true;
            updateNotice(false);
            prefs.edit().putBoolean(KEY_ACTIVE,false).putBoolean("finishing",true).putLong(KEY_HEARTBEAT,0L).apply();
            manager.removeUpdates(listener);
            locationHandler.post(() -> {
                try { long id=database.active(); database.finish(); if(singleMode&&id!=0&&database.payload(id).getJSONArray("points").length()==0)database.delete(id); } catch(Exception e) { prefs.edit().putString(KEY_ERROR,"路径保存失败："+e.getMessage()).apply(); }
                prefs.edit().putBoolean("finishing",false).apply();
                new Handler(getMainLooper()).post(() -> {stopForeground(STOP_FOREGROUND_REMOVE);foreground=false;stopSelf();});
            });
            return START_NOT_STICKY;
        }
        if(finishing)return START_NOT_STICKY;
        if(ACTION_SINGLE.equals(action)&&prefs.getBoolean(KEY_ACTIVE,false))return START_STICKY;
        if (!prefs.getBoolean(KEY_ACTIVE, false) && !ACTION_START.equals(action) && !ACTION_SINGLE.equals(action)) {
            stopSelf();
            return START_NOT_STICKY;
        }
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            fail("缺少精确定位权限，请打开应用重新授权");
            return START_NOT_STICKY;
        }
        try {
            singleMode=ACTION_SINGLE.equals(action)||(prefs.getBoolean(KEY_ACTIVE,false)&&prefs.getBoolean("single",false));
            if (!foreground) {
                Notification notice = notification("正在记录真实定位点");
                if (Build.VERSION.SDK_INT >= 29) {
                    startForeground(NOTIFICATION_ID, notice, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION);
                } else {
                    startForeground(NOTIFICATION_ID, notice);
                }
                foreground = true;
                locationHandler.post(heartbeat);
            }
            singleMode=ACTION_SINGLE.equals(action)||(prefs.getBoolean(KEY_ACTIVE,false)&&prefs.getBoolean("single",false));
            if(ACTION_CONFIG.equals(action))singleMode=prefs.getBoolean("single",false);
            if(!prefs.getBoolean(KEY_ACTIVE,false))prefs.edit().putBoolean("single",singleMode).putLong("singleStarted",System.currentTimeMillis()).putLong("recordStarted",System.currentTimeMillis()).apply();
            database.begin(singleMode);
            if(singleMode){locationHandler.removeCallbacks(singleTimeout);long remaining=120000L-(System.currentTimeMillis()-prefs.getLong("singleStarted",System.currentTimeMillis()));locationHandler.postDelayed(singleTimeout,Math.max(0,remaining));}
            prefs.edit().putBoolean(KEY_ACTIVE, true).putBoolean("finishing",false).remove(KEY_ERROR).apply();
            if (lastMovingElapsed == 0) {
                lastMovingElapsed = SystemClock.elapsedRealtime();
                locationHandler.postDelayed(idleCheck, 180000L);
            }
            configure();
            locationHandler.post(() -> updateNotice(true));
        } catch (Exception problem) {
            fail("定位服务启动失败：" + problem.getClass().getSimpleName());
            return START_NOT_STICKY;
        }
        return START_STICKY;
    }

    private Notification notification(String text) {
        Intent open = new Intent(this, MainActivity.class);
        PendingIntent content = PendingIntent.getActivity(this, 1, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Intent stop = new Intent(this, TrackService.class).setAction(ACTION_STOP);
        PendingIntent stopIntent = PendingIntent.getService(this, 2, stop,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        String title = finishing ? "途记 · 正在保存" : singleMode ? "途记 · 单点定位" : "途记 · 记录沿途";
        Notification notice = new Notification.Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.ic_stat_location)
                .setContentTitle(title)
                .setOnlyAlertOnce(true)
                .setContentText(text)
                .setContentIntent(content)
                .setOngoing(true)
                .addAction(new Notification.Action.Builder(
                        android.R.drawable.ic_media_pause, "停止记录", stopIntent).build())
                .build();
        // 超级岛使用更短的文案：主标题标识状态，主要说明给数量，次要说明给时长。
        return XiaomiIsland.decorate(this, notice, islandTitle(), islandContent(), islandSubContent(),
                finishing, !finishing, islandStopUri());
    }

    /** 岛上显示的主标题，保持短且稳定。 */
    private String islandTitle() {
        return finishing ? "正在保存" : singleMode ? "单点定位" : "记录沿途";
    }

    /** 岛上显示的主要说明。 */
    private String islandContent() {
        if (finishing) return "整理定位点并保存路径";
        if (singleMode) return "等待新鲜卫星定位";
        try {
            return "已记录 " + database.count() + " 点";
        } catch (Exception e) {
            return "正在记录";
        }
    }

    /** 岛上显示的次要说明，缺省不显示。 */
    private String islandSubContent() {
        if (finishing || singleMode) return "";
        long start = getSharedPreferences(PREFS, MODE_PRIVATE).getLong("recordStarted", System.currentTimeMillis());
        long minutes = Math.max(0, (System.currentTimeMillis() - start) / 60000);
        return minutes + " 分钟";
    }

    /**
     * 岛上“停止”按钮的目标 URI。
     * 官方模板库要求 actionIntent 指向的组件在清单里声明 exported="true"，故指向 IslandActionReceiver。
     */
    private String islandStopUri() {
        Intent stop = new Intent(this, IslandActionReceiver.class).setAction(IslandActionReceiver.ACTION_ISLAND_STOP);
        return stop.toUri(Intent.URI_INTENT_SCHEME);
    }

    private void updateNotice(boolean probe) {
        if(!foreground) return;
        if(probe)XiaomiIsland.probe(this,false);
        long now=SystemClock.elapsedRealtime();
        if(!probe&&!finishing&&now-lastNoticeElapsed<10000L)return;
        lastNoticeElapsed=now;
        try {
            long start=getSharedPreferences(PREFS,MODE_PRIVATE).getLong("recordStarted",System.currentTimeMillis());
            long minutes=Math.max(0,(System.currentTimeMillis()-start)/60000);
            String detail=finishing?"整理定位点并保存路径…":singleMode?"等待新鲜卫星定位，成功后自动保存":"已记录"+database.count()+"点 · "+minutes+"分钟";
            ((NotificationManager)getSystemService(NOTIFICATION_SERVICE)).notify(NOTIFICATION_ID,notification(detail));
        }catch(Exception ignored){/* Denied notification permission must not stop GPS. */}
    }

    private void configure() {
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            throw new SecurityException("Fine location permission was revoked");
        }
        manager.removeUpdates(listener);
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        boolean photo = prefs.getInt(KEY_MODE, 0) == 1;
        long gpsMs = singleMode ? 1000L : photo ? 10000L : slowMode ? 60000L : 30000L;
        boolean any = false;
        if (manager.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
            // Time matching needs fresh fixes even when the photographer is stationary.
            manager.requestLocationUpdates(LocationManager.GPS_PROVIDER, gpsMs, 0f,
                    listener, locationThread.getLooper());
            any = true;
        }
        if (manager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)) {
            manager.requestLocationUpdates(LocationManager.NETWORK_PROVIDER, 60000L, 0f,
                    listener, locationThread.getLooper());
            any = true;
        }
        if (!any) throw new IllegalStateException("Location providers disabled");
    }

    private void accept(Location fix) {
        if (finishing || !getSharedPreferences(PREFS,MODE_PRIVATE).getBoolean(KEY_ACTIVE,false) || fix.isFromMockProvider()) return;
        long elapsedAge = SystemClock.elapsedRealtimeNanos() - fix.getElapsedRealtimeNanos();
        // Android may deliver genuine fixes late after Doze or as a batch. Preserve
        // their original fix timestamps for photo matching instead of discarding them.
        if (elapsedAge < 0 || elapsedAge > 86_400_000_000_000L || fix.getTime() <= 0L) return;
        if (!fix.hasAccuracy() || !Float.isFinite(fix.getAccuracy()) ||
                fix.getAccuracy() < 0f || fix.getAccuracy() > 100f) return;
        if (!Double.isFinite(fix.getLatitude()) || !Double.isFinite(fix.getLongitude()) ||
                Math.abs(fix.getLatitude()) > 90 || Math.abs(fix.getLongitude()) > 180) return;
        if (fix.hasSpeed() && (!Float.isFinite(fix.getSpeed()) || fix.getSpeed() < 0f)) fix.removeSpeed();
        if (fix.hasBearing() && !Float.isFinite(fix.getBearing())) fix.removeBearing();
        if(singleMode&&(elapsedAge>15_000_000_000L||!LocationManager.GPS_PROVIDER.equals(fix.getProvider())))return;
        Location previous = lastAccepted;
        if (Build.VERSION.SDK_INT >= 34 && altitudeConverter != null &&
                fix.hasAltitude() && !fix.hasMslAltitude()) {
            try {
                altitudeConverter.addMslAltitudeToLocation(this, fix);
            } catch (Exception ignored) {
                // No trustworthy MSL height: retain lat/lon and export alt=null.
            }
        }
        try {
            boolean added=database.add(fix);
            if(added&&!singleMode)updateNotice(false);
            if(singleMode&&added){getSharedPreferences(PREFS,MODE_PRIVATE).edit().putBoolean(KEY_ACTIVE,false).apply();locationHandler.removeCallbacks(singleTimeout);new Handler(getMainLooper()).post(this::finishRecording);return;}
            getSharedPreferences(PREFS, MODE_PRIVATE).edit().remove(KEY_ERROR).apply();
        } catch (Exception problem) {
            getSharedPreferences(PREFS, MODE_PRIVATE).edit()
                    .putString(KEY_ERROR, "保存定位点失败：" + problem.getClass().getSimpleName()).apply();
            return;
        }
        // Delayed historical fixes belong in the route but cannot drive current
        // movement and power-state decisions.
        if (elapsedAge > 120_000_000_000L ||
                (previous != null && fix.getTime() < previous.getTime())) return;
        lastAccepted = new Location(fix);
        if (getSharedPreferences(PREFS, MODE_PRIVATE).getInt(KEY_MODE, 0) == 1) return;
        float moved = previous == null ? 0f : previous.distanceTo(fix);
        float movementThreshold = previous == null ? 35f :
                Math.max(35f, 2f * (previous.getAccuracy() + fix.getAccuracy()));
        boolean trustedSpeed = LocationManager.GPS_PROVIDER.equals(fix.getProvider()) &&
                fix.getAccuracy() <= 30f && fix.hasSpeed() && fix.getSpeed() >= 1.5f;
        boolean moving = trustedSpeed || moved >= movementThreshold;
        long now = SystemClock.elapsedRealtime();
        if (moving) {
            lastMovingElapsed = now;
            locationHandler.removeCallbacks(idleCheck);
            locationHandler.postDelayed(idleCheck, 180000L);
        }
        boolean shouldSlow = lastMovingElapsed != 0 && now - lastMovingElapsed >= 180000L;
        if (shouldSlow != slowMode) {
            slowMode = shouldSlow;
            try { configure(); } catch (Exception ignored) { /* status appears in the app */ }
        }
    }

    private void fail(String message) {
        getSharedPreferences(PREFS, MODE_PRIVATE).edit()
                .putBoolean(KEY_ACTIVE, false).putLong(KEY_HEARTBEAT, 0L)
                .putString(KEY_ERROR, message).apply();
        if (foreground) stopForeground(STOP_FOREGROUND_REMOVE);
        foreground = false;
        try {
            PendingIntent open = PendingIntent.getActivity(this, 4,
                    new Intent(this, MainActivity.class),
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            NotificationManager notifications = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            notifications.notify(ERROR_NOTIFICATION_ID, new Notification.Builder(this, ERROR_CHANNEL)
                    .setSmallIcon(R.drawable.ic_stat_location)
                    .setContentTitle("NEF轨迹已停止")
                    .setContentText(message)
                    .setContentIntent(open)
                    .setAutoCancel(true)
                    .build());
        } catch (Exception ignored) { /* Notification permission may be denied. */ }
        stopSelf();
    }

    @Override public void onTaskRemoved(Intent rootIntent) {
        // Keep the user-started foreground service running when the UI task is swiped away.
        super.onTaskRemoved(rootIntent);
    }

    @Override public void onDestroy() {
        manager.removeUpdates(listener);
        locationHandler.removeCallbacks(idleCheck);
        locationHandler.removeCallbacks(heartbeat);
        locationHandler.removeCallbacks(singleTimeout);
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        if (!prefs.getBoolean(KEY_ACTIVE, false)) {
            prefs.edit().putLong(KEY_HEARTBEAT, 0L).apply();
        }
        locationThread.quitSafely();
        database.close();
        finishing=false;
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
