package app.nefgpstrack;

import android.app.Notification;
import android.app.NotificationManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.drawable.Icon;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import org.json.JSONArray;
import org.json.JSONObject;

import java.lang.reflect.Method;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/**
 * 小米超级岛（焦点通知）本地适配层。
 *
 * 依据小米官方《小米超级岛通知模板库》实现，通知 extra 使用三个键：
 * miui.focus.param（JSON 字符串）、miui.focus.pics（Bundle&lt;String,Icon&gt;）、miui.focus.actions（Bundle，本版不使用）。
 *
 * 设计约束：
 * 1) 任何一步失败都不得影响普通前台通知与定位服务，全部异常就地吞掉并记录到诊断信息；
 * 2) 能力判定为三态：支持 / 不支持 / 未知。隐藏 API 读取失败只记为“未知”，不再一票否决整个功能；
 * 3) 动作按钮使用模板库的“方式二”（纯 JSON 的 actionIntent），避免向 SystemUI 传递类型不确定的 Parcelable。
 *
 * 重要边界：本适配仍需小米为应用开通焦点通知权限（canShowFocus 为 true）才可能真正上岛；
 * 未获授权时系统会忽略 param，本类只负责把可诊断的状态如实报出来。
 */
final class XiaomiIsland {
    /** 焦点通知参数键。 */
    static final String KEY_PARAM = "miui.focus.param";
    /** 图片资源键：值必须是 Icon。 */
    static final String KEY_PICS = "miui.focus.pics";
    /** 动作资源键（方式一）。本版不使用，保留常量便于日后接入。 */
    static final String KEY_ACTIONS = "miui.focus.actions";

    /** 图片 key 必须以 miui.focus.pic_ 前缀命名，JSON 中的值即这里的 key。 */
    static final String PIC_ROUTE = "miui.focus.pic_route";
    static final String PIC_ROUTE_DARK = "miui.focus.pic_route_dark";
    static final String PIC_FUNCTION = "miui.focus.pic_function";
    static final String PIC_ACTION_STOP = "miui.focus.pic_action_stop";

    /** 动作 key 必须以 miui.focus.action_ 前缀命名。 */
    static final String ACTION_STOP = "miui.focus.action_stop";

    /** 焦点通知协议最低版本。 */
    static final int MIN_PROTOCOL = 3;
    /** 默认业务标识；正式上岛需替换为小米审核通过的值。 */
    static final String DEFAULT_BUSINESS = "gps_track";
    /** 测试通知的 id 与渠道。 */
    static final int TEST_NOTIFICATION_ID = 1002;
    static final String TEST_CHANNEL = "island_test";

    private static final int UNKNOWN = -1, NO = 0, YES = 1;
    private static final String[] PROVIDER_AUTHORITIES = {
            "miui.statusbar.notification.public",
            "miui.statusbar.notification"
    };

    private static volatile long checkedAt;
    private static volatile int protocol;
    private static volatile String protocolError = "";
    private static volatile int featureFlag = UNKNOWN;
    private static volatile String featureError = "";
    private static volatile int canShow = UNKNOWN;
    private static volatile String canShowError = "";
    private static volatile String canShowVia = "";
    private static volatile String lastError = "";
    private static volatile String lastAttemptAt = "";
    private static volatile String lastPayload = "";

    private XiaomiIsland() {}

    /* ---------------- 偏好 ---------------- */

    private static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences(TrackService.PREFS, Context.MODE_PRIVATE);
    }

    static boolean enabled(Context c) {
        return prefs(c).getBoolean("islandEnabled", true);
    }

    static String business(Context c) {
        String value = prefs(c).getString("islandBusiness", DEFAULT_BUSINESS);
        return value == null || value.trim().isEmpty() ? DEFAULT_BUSINESS : value.trim();
    }

    static void setBusiness(Context c, String value) {
        prefs(c).edit().putString("islandBusiness", value == null ? "" : value.trim()).apply();
    }

    /* ---------------- 能力探测 ---------------- */

    /**
     * 探测系统超级岛能力。结果缓存 60 秒；force 为 true 时强制刷新。
     * 本方法不抛异常：所有失败都记录到诊断字段。
     */
    static synchronized void probe(Context c, boolean force) {
        long now = android.os.SystemClock.elapsedRealtime();
        if (!force && checkedAt != 0 && now - checkedAt < 60000L) return;

        protocolError = "";
        try {
            protocol = Settings.System.getInt(c.getContentResolver(), "notification_focus_protocol", 0);
        } catch (Exception e) {
            protocol = 0;
            protocolError = describe(e);
        }

        if (featureFlag != YES || force) readFeatureFlag(c);

        canShowError = "";
        canShowVia = "";
        canShow = UNKNOWN;
        if (protocol >= MIN_PROTOCOL) queryCanShowFocus(c);

        checkedAt = now;
    }

    /** 读取 persist.sys.feature.island。隐藏 API 在 Android 9+ 可能被拦截，失败只记为“未知”。 */
    private static void readFeatureFlag(Context c) {
        featureFlag = UNKNOWN;
        featureError = "";
        try {
            Class<?> clazz = Class.forName("android.os.SystemProperties");
            Method method = clazz.getDeclaredMethod("getBoolean", String.class, boolean.class);
            method.setAccessible(true);
            Object value = method.invoke(null, "persist.sys.feature.island", false);
            featureFlag = Boolean.TRUE.equals(value) ? YES : NO;
        } catch (Throwable t) {
            featureFlag = UNKNOWN;
            featureError = describe(t);
        }
    }

    /** 依次尝试已知的 provider authority 与调用方式，记录成功的那一个。 */
    private static void queryCanShowFocus(Context c) {
        Bundle args = new Bundle();
        args.putString("package", c.getPackageName());
        for (String authority : PROVIDER_AUTHORITIES) {
            try {
                Bundle result = c.getContentResolver().call(
                        Uri.parse("content://" + authority), "canShowFocus", null, args);
                if (result == null) {
                    canShowError = authority + " 返回空结果";
                    continue;
                }
                if (!result.containsKey("canShowFocus")) {
                    canShowError = authority + " 未返回 canShowFocus 字段";
                    continue;
                }
                canShow = result.getBoolean("canShowFocus", false) ? YES : NO;
                canShowVia = authority;
                canShowError = "";
                return;
            } catch (Exception e) {
                canShowError = authority + ": " + describe(e);
            }
        }
    }

    /**
     * 是否具备尝试上岛的条件。
     * featureFlag 与 canShowFocus 只有“明确为否”才阻塞：读取不到时按“未知”放行，
     * 由系统自行忽略无权限的 param，避免某个隐藏 API 被拦截就彻底用不了。
     */
    static boolean eligible(Context c) {
        return enabled(c)
                && notificationsEnabled(c)
                && protocol >= MIN_PROTOCOL
                && featureFlag != NO
                && canShow != NO;
    }

    private static boolean notificationsEnabled(Context c) {
        try {
            NotificationManager manager = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
            return manager != null && manager.areNotificationsEnabled();
        } catch (Exception e) {
            return false;
        }
    }

    /** 第一个不满足的条件，用于界面提示；全部满足时返回空串。 */
    static String blockedBy(Context c) {
        if (!enabled(c)) return "已关闭尝试";
        if (!notificationsEnabled(c)) return "通知未授权";
        if (protocol < MIN_PROTOCOL) return "系统焦点通知协议版本不足";
        if (featureFlag == NO) return "系统未开启超级岛";
        if (canShow == NO) return "应用暂无焦点通知权限";
        return "";
    }

    /* ---------------- 状态与诊断 ---------------- */

    static JSONObject status(Context c) throws Exception {
        String blocked = blockedBy(c);
        String text;
        if (!enabled(c)) text = "已关闭尝试，记录仍使用普通通知。";
        else if (!notificationsEnabled(c)) text = "通知未授权，请先允许途记通知。";
        else if (protocol < MIN_PROTOCOL) text = "当前系统未报告焦点通知协议（读到 " + protocol + "），使用普通通知。";
        else if (featureFlag == NO) text = "系统未开启超级岛，使用普通通知。";
        else if (canShow == NO) text = "系统支持超级岛，但途记尚无焦点通知权限，使用普通通知。";
        else if (canShow == UNKNOWN) text = "无法确认焦点通知权限（" + canShowError + "），仍会尝试。";
        else text = "已具备尝试条件；实际显示需在记录时确认。";
        return new JSONObject()
                .put("enabled", enabled(c))
                .put("supported", featureFlag != NO)
                .put("protocol", protocol)
                .put("permission", canShow == YES)
                .put("business", business(c))
                .put("blockedBy", blocked)
                .put("status", text);
    }

    /** 完整诊断：每个闸门的取值、失败原因与最近一次发送结果。 */
    static JSONObject diagnose(Context c) throws Exception {
        JSONObject gates = new JSONObject()
                .put("switch", enabled(c) ? "on" : "off")
                .put("notifications", notificationsEnabled(c))
                .put("protocol", protocol)
                .put("protocolError", protocolError)
                .put("featureFlag", featureFlag == YES ? "true" : featureFlag == NO ? "false" : "unknown")
                .put("featureFlagError", featureError)
                .put("canShowFocus", canShow == YES ? "true" : canShow == NO ? "false" : "unknown")
                .put("canShowFocusVia", canShowVia)
                .put("canShowFocusError", canShowError)
                .put("channelImportance", channelImportance(c))
                .put("business", business(c));
        JSONObject device = new JSONObject()
                .put("manufacturer", String.valueOf(Build.MANUFACTURER))
                .put("brand", String.valueOf(Build.BRAND))
                .put("model", String.valueOf(Build.MODEL))
                .put("androidSdk", Build.VERSION.SDK_INT)
                .put("incremental", String.valueOf(Build.VERSION.INCREMENTAL))
                .put("display", String.valueOf(Build.DISPLAY));
        JSONObject last = new JSONObject()
                .put("at", lastAttemptAt)
                .put("ok", lastError.isEmpty())
                .put("error", lastError)
                .put("payload", lastPayload);
        return new JSONObject()
                .put("eligible", eligible(c))
                .put("blockedBy", blockedBy(c))
                .put("status", status(c).getString("status"))
                .put("gates", gates)
                .put("device", device)
                .put("last", last);
    }

    private static String channelImportance(Context c) {
        try {
            NotificationManager manager = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
            if (manager == null) return "unknown";
            android.app.NotificationChannel channel = manager.getNotificationChannel(TrackService.CHANNEL);
            if (channel == null) return "absent";
            switch (channel.getImportance()) {
                case NotificationManager.IMPORTANCE_NONE: return "none";
                case NotificationManager.IMPORTANCE_MIN: return "min";
                case NotificationManager.IMPORTANCE_LOW: return "low";
                case NotificationManager.IMPORTANCE_DEFAULT: return "default";
                case NotificationManager.IMPORTANCE_HIGH: return "high";
                default: return "unspecified";
            }
        } catch (Exception e) {
            return "unknown";
        }
    }

    /* ---------------- 通知装饰 ---------------- */

    /**
     * 为前台通知附加超级岛参数。
     *
     * @param title      岛与普通通知共用的标题
     * @param content    主要说明，例如“已记录 12 点”
     * @param subContent 次要说明，例如“3 分钟”
     * @param stopAction 动作按钮的 PendingIntent URI，可为 null
     */
    static Notification decorate(Context c, Notification notification, String title, String content,
                                 String subContent, boolean finishing, boolean canStop, String stopUri) {
        try {
            lastAttemptAt = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US).format(new Date());
            if (!eligible(c)) {
                lastError = blockedBy(c);
                lastPayload = "";
                return notification;
            }
            String payload = buildParam(c, title, content, subContent, finishing, canStop, stopUri).toString();
            Bundle pics = new Bundle();
            pics.putParcelable(PIC_ROUTE, Icon.createWithResource(c, R.drawable.ic_island_route));
            pics.putParcelable(PIC_ROUTE_DARK, Icon.createWithResource(c, R.drawable.ic_island_route_dark));
            pics.putParcelable(PIC_FUNCTION, Icon.createWithResource(c, R.drawable.ic_island_function));
            pics.putParcelable(PIC_ACTION_STOP, Icon.createWithResource(c, R.drawable.ic_island_stop));
            notification.extras.putBundle(KEY_PICS, pics);
            notification.extras.putString(KEY_PARAM, payload);
            lastError = "";
            lastPayload = payload;
        } catch (Throwable t) {
            // 普通通知必须保持可用：任何异常只记录，不外抛。
            lastError = describe(t);
            lastPayload = "";
        }
        return notification;
    }

    /**
     * 构造 miui.focus.param。结构取自官方模板库：文本组件1(baseInfo.type=1)、
     * 识别图形组件(picInfo)、动作按钮“方式二”(actionIntent/actionIntentType)。
     */
    static JSONObject buildParam(Context c, String title, String content, String subContent,
                                 boolean finishing, boolean canStop, String stopUri) throws Exception {
        JSONObject picInfo = new JSONObject()
                .put("type", 3)
                .put("pic", PIC_ROUTE)
                .put("picDark", PIC_ROUTE_DARK);

        JSONObject baseInfo = new JSONObject()
                .put("type", 1)
                .put("title", title)
                .put("content", content)
                .put("subContent", subContent)
                .put("picFunction", PIC_FUNCTION)
                .put("showDivider", true)
                .put("showContentDivider", true);

        JSONObject bigArea = new JSONObject()
                .put("picInfo", picInfo)
                .put("baseInfo", baseInfo)
                .put("actionInfo", new JSONObject().put("clickWithCollapse", false));

        JSONObject smallArea = new JSONObject().put("picInfo", picInfo);

        JSONObject island = new JSONObject()
                .put("islandProperty", 1)
                .put("islandOrder", false)
                .put("islandTimeout", 3600)
                .put("bigIslandArea", bigArea)
                .put("smallIslandArea", smallArea);

        JSONObject param = new JSONObject()
                .put("protocol", 1)
                .put("business", business(c))
                .put("updatable", true)
                .put("reopen", "reopen")
                .put("enableFloat", false)
                .put("islandFirstFloat", false)
                .put("filterWhenNoPermission", false)
                .put("ticker", title)
                .put("tickerPic", PIC_ROUTE)
                .put("aodTitle", title)
                .put("aodPic", PIC_ROUTE)
                .put("param_island", island)
                .put("baseInfo", baseInfo)
                .put("picInfo", picInfo);

        if (canStop && stopUri != null && !stopUri.isEmpty()) {
            // 方式二：纯 JSON 描述按钮，避免向 SystemUI 传类型不确定的 Parcelable。
            param.put("actions", new JSONArray().put(new JSONObject()
                    .put("type", 0)
                    .put("actionIcon", PIC_ACTION_STOP)
                    .put("actionIconDark", PIC_ACTION_STOP)
                    .put("actionTitle", finishing ? "保存中" : "停止")
                    .put("actionIntentType", 3)
                    .put("actionIntent", stopUri)
                    .put("clickWithCollapse", false)));
        }
        return new JSONObject().put("param_v2", param);
    }

    /* ---------------- 测试通知 ---------------- */

    /**
     * 发送一条独立的测试焦点通知，用于在不开始记录的情况下判断本机是否真的上岛。
     * 通知 30 秒后自动消失，返回实际下发的 param JSON。
     */
    static String sendTest(Context c) {
        try {
            probe(c, true);
            NotificationManager manager = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
            if (manager == null) return "无法获取通知服务";
            manager.createNotificationChannel(new android.app.NotificationChannel(
                    TEST_CHANNEL, "超级岛测试", NotificationManager.IMPORTANCE_LOW));
            String title = "途记 · 超级岛测试";
            String content = eligible(c) ? "本条应显示在超级岛上" : "条件未满足：" + blockedBy(c);
            Notification.Builder builder = new Notification.Builder(c, TEST_CHANNEL)
                    .setSmallIcon(R.drawable.ic_stat_location)
                    .setContentTitle(title)
                    .setContentText(content)
                    .setOnlyAlertOnce(true)
                    .setOngoing(true)
                    .setTimeoutAfter(30000L);
            Notification notice = decorate(c, builder.build(), title, content, "", false, false, null);
            manager.notify(TEST_NOTIFICATION_ID, notice);
            return lastError.isEmpty() ? lastPayload : "未下发参数：" + lastError;
        } catch (Throwable t) {
            lastError = describe(t);
            return "测试通知失败：" + lastError;
        }
    }

    /* ---------------- 工具 ---------------- */

    private static String describe(Throwable t) {
        String message = t.getMessage();
        return t.getClass().getSimpleName() + (message == null || message.isEmpty() ? "" : ": " + message);
    }
}
