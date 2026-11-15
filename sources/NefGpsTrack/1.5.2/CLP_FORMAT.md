# CLP1 协议（途记 1.5.2）

## 加密和基本字段

保持 CLP1 文件头、nef-gps-track/1 JSON schema 及既有固定互通口令不变。从源码构建时的口令配置见仓库根目录的 BUILD.md。

- 0–3 字节为 ASCII `CLP1`；4–7 字节为大端 PBKDF2 迭代次数 310000；8–23 字节为随机盐；24–35 字节为随机 12 字节 nonce。
- PBKDF2-HMAC-SHA256 输出 32 字节；36 字节头部作 AES-256-GCM AAD，后跟 UTF-8 JSON 密文及 16 字节认证标签。每次导出生成新的盐和 nonce。
- `createdUtcMs`、点的 `t` 均为 UTC 毫秒。`lat` / `lon` 为 WGS84 经纬度，`alt` 为平均海平面高度（MSL，米）或 null。`hacc` 为水平精度米或 null，`speed` 米/秒，`bearing` 度，`provider` 定位提供者。
- `mode=track` 是连续轨迹；`mode=single` 明确表示单个观测可为照片补录作后备，照片 GPS 时间仍用拍摄 UTC。原观测 t 不改变。
- `rawPoints` 保留原始观测，手机停止时通过 `robust-stop-v2` 平滑水平位置到 `points`，保持点数与时刻；手机不输出曲线。

## 1.5.2 可选高度元数据

所有新增字段均为可选。旧文件没有字段时，原有 `alt` 按历史 MSL 语义读取；旧客户端可忽略扩展字段。

| 字段 | 含义 |
| --- | --- |
| `ellipsoidAlt` | 原始 WGS84 椭球高，米；从不直接冒充 `alt` |
| `verticalAccuracy` | 椭球高精度估计，米或 null |
| `altAccuracy` | MSL 高度精度估计，米或 null |
| `altSource` | `provided-msl` / `androidx-msl` / `legacy-msl` / `unknown` / `conversion-failed`；电脑派生点可为 `interpolated-msl` |
| `altProvider` | 被选高度观测的原定位提供者 |
| `altLat` / `altLon` / `altHacc` | 高度观测原位置与水平精度，用于同刻合并的空间相容检查 |
| `altOriginal` | 电脑端平滑/补缺前的高度值，可为 null；避免重导入时重复处理 |
| `altSourceBeforeMs` / `altSourceAfterMs` | 电脑补缺所依赖的前后已知 MSL 时刻 |

手机 `altitudeAcquisition=msl-compat-v1`：优先接受系统有效 MSL，否则调用 AndroidX：API 26–33 使用随库离线重力模型，API 34+ 委托系统转换器。无法转换时保存原始椭球高并保留 `alt=null`。同刻不同提供者的高度只在空间相容时合并，记录高度本身的来源位置。

## 电脑曲线与补缺

`curve.version=pchip-4d-v3`。按时间分别构造纬度、短路径展开的经度及 MSL 高度子曲线，采用既有保形三次 Hermite 插值。外来旧 `curve` 系数不受信任，读入后由有效节点重建。

`alt` 子曲线只使用有 MSL 的观测，不让 `interpolated-msl` 点反过来充当新测量。相邻已知 MSL 超过 120000 毫秒时断开；区段内缺失节点可估算，首尾外、长缺口和整条无高度返回 null。分段端点斜率与 `robust-alt-v2` 海拔平滑也不跨此缺口。水平长间隔匹配仍按既有规则标注 `curve-long-gap`，与高度是否可用分开判断。

电脑派生载荷标记 `altitudeReconstruction=bounded-msl-v1`，保留 `rawPoints` 与 `altOriginal`，缺值补出时标 `interpolated-msl` 和来源时刻。精确命中缺海拔点的照片也走同一补缺判据。120 秒上限只是软件保护策略，估算不能等同实测，陡坡等场景仍可能有误差。

已有派生文件若无法找到原始输入则保持原高度，不反复平滑，并记录 `altitudeInputUnavailable`。用户历史 CLP 文件本身不被修改。旧客户端仍可解析新文件，但会按其自身的旧曲线策略处理；新版缺口保护应使用 1.5.2 电脑端。

## 验证

`qa/clp1_test_vector.json`、`qa/verify_clp1_vector.py` 与 `qa/ClpVectorCheck.java` 验证 Java/Python 加密一致性。采集与曲线回归分别见 `qa/altitude-recording-152.md`、`qa/altitude-152-notes.md`。两端 APK/EXE 内公共 UI 必须与源文件逐字节一致。