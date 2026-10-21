package app.nefgpstrack;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;

/**
 * 超级岛动作按钮的入口。
 *
 * 官方模板库要求 actionIntent 对应的组件在清单中显式声明 exported="true"，
 * 否则部分机型点击岛上的按钮没有反应。
 *
 * 安全边界：本接收器只接受 ISLAND_STOP 一个动作、不接收任何参数、不返回数据，
 * 并且只在确实处于记录中时才转发停止请求；其余动作一律忽略。
 */
public final class IslandActionReceiver extends BroadcastReceiver {
    static final String ACTION_ISLAND_STOP = "app.nefgpstrack.ISLAND_STOP";

    @Override public void onReceive(Context context, Intent intent) {
        if (intent == null || !ACTION_ISLAND_STOP.equals(intent.getAction())) return;
        try {
            // 只有记录进行中（前台服务在跑）才转发，避免后台启动前台服务触发系统限制。
            SharedPreferences prefs = context.getSharedPreferences(TrackService.PREFS, Context.MODE_PRIVATE);
            if (!prefs.getBoolean(TrackService.KEY_ACTIVE, false)) return;
            context.startForegroundService(
                    new Intent(context, TrackService.class).setAction(TrackService.ACTION_STOP));
        } catch (Exception ignored) {
            // 记录已结束或系统限制后台启动时无需额外处理，下一次刷新会纠正界面状态。
        }
    }
}
