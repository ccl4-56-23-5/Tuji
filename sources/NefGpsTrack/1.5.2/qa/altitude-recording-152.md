# 1.5.2 Android 海拔采集修正

## 已核实的旧行为与修正

- 旧版只在 API 34 以上读取 `Location.hasMslAltitude()`，较早 Android 即使提供椭球高也导出 `alt=null`。本版复用 AndroidX `core-location-altitude:1.0.1`，支持本应用的 API 26+ 范围；工作仍在定位工作线程执行。该库在 API 34 以前使用随包 geoid 数据库，在 API 34 及以上委托系统 `AltitudeConverter`，因此并非系统转换失败后的第二套独立后备模型。
- 旧版同一时间戳只比较水平精度。后来的较精确水平点会覆盖已有海拔，后来的有海拔点又可能被水平比较挡住。本版分别选择水平位置和海拔观测。只允许**相同原始时间戳**且水平位置相容的观测组合，不将相邻时刻的高度硬拷过来。
- 相容阈值为 `distance <= max(10 m, min(100 m, haccA + haccB))`。组合时再次检查原始海拔观测位置，防止连续替换逐步把高度拖到远处。MSL 优先于仅有椭球高；同类高度优先采用较好的已知垂直精度，双方精度未知时以原海拔观测的水平精度择优。
- 单点定位原来在首个合格 GPS 点立即结束，有时卫星水平解算先于高度出现。本版首次获得水平点后最多再等 10 秒；总超时仍为 120 秒。获得带 MSL 的真实点即结束，否则保存等待窗口内水平精度最好的真实点并明确保持海拔空值。结束后仍只有一个点。

## 数据与兼容性

`alt` 始终表示 MSL 米或 `null`。无高度、转换失败或不同时间的点都不会填 `0`、沿用前一点高度，或把椭球高当作海拔。

DB 从版本 3 升到 4，只增加可空列。旧数据的非空海拔标记 `legacy-msl`；已有保存路线的缓存载荷保持原样，历史 CLP 不改写。新载荷标记 `altitudeAcquisition=msl-compat-v1`，现有 schema 与 CLP 加密头不变。

新增点字段：

| 字段 | 含义 |
| --- | --- |
| `ellipsoidAlt` | 高度来源定位点的原始 WGS84 椭球高，米或 null |
| `verticalAccuracy` | 该椭球高的原始垂直精度，米或 null |
| `altAccuracy` | MSL 高度精度，米或 null |
| `altSource` | `provided-msl` / `androidx-msl` / `legacy-msl` / `unknown` / `conversion-failed` |
| `altProvider` | 海拔观测来源 provider，可与水平点的 provider 不同 |
| `altHacc`, `altLat`, `altLon` | 海拔观测来源的水平精度与原始位置，供审计和合并边界判断 |

`rawPoints` 延续同时间去重后的定位记录语义。水平位置和高度可来源于同一时刻的不同 provider，来源由上述字段明确记录；它不是所有被拒绝回调的完整日志。`points` 的水平平滑仍由既有 `TrackSmoother` 完成，不额外改变原始高度。海拔插值及相应估算标记在电脑端单独处理。

## 验证入口与边界

`android/app/src/test/java/app/nefgpstrack/AltitudeRecordingTest.java` 使用 Robolectric 的 API 26 和 API 34 环境，执行实际 Android `Location`、SQLite、JSON 及 AndroidX 随包 geoid 资源。覆盖离线椭球高转换、原生 MSL 不二次转换、缺值、转换失败保留原始高度、去重择优、空间不相容、来源位置约束、不同时间不传播高度、保存缓存、旧路由保护、版本 3 升级和单点等待选择。

执行：`gradlew.bat :app:testDebugUnitTest`。构建与测试结果由本版交付验证记录保存，本文件本身不代替执行证据。

无 Android 真机连接时，不能据此宣称锁屏 GPS、厂商定位 provider、耗电或真实海拔精度已经验收。转换只能利用设备已有的椭球高；完全没有垂直观测、系统转换失败或资源不可读时仍可能缺海拔，失败时保留原始椭球高及失败来源。单点最多 10 秒等待也不保证取得高度。

首次 API 26 资源转换回归发现测试跑在 Robolectric 主线程，触发 AndroidX Room 的 `assertNotMainThread`。修正测试为与实际服务一致的工作线程执行，同时保留直接 converter 调用以显示原始异常，未移除精度断言或用模拟高度代替真实转换。生产服务的转换位置本来就在定位工作线程。

## 选型依据（2026-11-06 核实）

- [AndroidX AltitudeConverterCompat 官方 API](https://developer.android.com/reference/androidx/core/location/altitude/AltitudeConverterCompat)：离线资源转换 WGS84 椭球高到 MSL，必须在工作线程调用。
- [LocationCompat 官方 API](https://developer.android.com/reference/androidx/core/location/LocationCompat)：在 API 34 以下通过 Location extras 兼容保存 MSL 与精度。
- [AndroidX Core 发布记录](https://developer.android.com/jetpack/androidx/releases/core)：`core-location-altitude:1.0.1` 于 2026-10-21 发布。
- [Robolectric 官方入门](https://robolectric.org/getting-started/)：本版新增回归使用 4.17 与 JUnit。

采用上述已维护的转换库，避免自研 geoid 模型、网络海拔查询及其离线/隐私/维护成本。
