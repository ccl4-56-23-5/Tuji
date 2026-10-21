# Android途记1.5.1

版本码13，包名`app.nefgpstrack`及签名不变，可覆盖升级1.3.0、1.4.0beta2、1.4.0、1.4.1、1.4.2与1.5.0。构建、采集、数据库、授权、超级岛和实机验收见上级完整维护文档.md。默认ASCII构建目录D:\Codex\nefgpstrack-151-build，缓存不进源码归档。

**手机端自1.5.0起只做第一步**（不是1.5.1的改动：`sources\NefGpsTrack\1.5.0`树里已经没有`TrackCurve.java`，`TrackDb.java`也不含`curve`，与1.5.1逐字节一致）：录制结束时用`TrackSmoother`滤除GPS定位漂移，结果写进CLP的`points`；第二步「插值形成平滑曲线」已移交电脑端，导出的CLP不再包含`curve`，回看页节点之间为直线。

**1.5.1手机端未改动**：`TrackSmoother.java`与`TrackDb.java`都没动——逐文件比对过，1.5.1与1.5.0的`android`树里**没有任何`.java`文件不同**，差异只在`app/build.gradle.kts`（版本码/版本名）、`build-release.ps1`（ASCII构建目录）、`app/src/main/assets/ui/*`（从`shared/ui`同步的界面副本）与文档。海拔平滑（`smooth_altitude()`）与四维曲线（`curve.py`的`pchip-4d-v2`与`alt`子曲线）都在电脑端完成，手机端不参与，也不需要为它们做跨端 parity。**电脑端的安装式发布（安装器、`data\路径库`与`data\程序数据`、可读轨迹文件名、照片页右列两面板）与手机端无关**：本端不读、不写安装路径下的数据，导出仍是原来的文件选择方式，回看页行为与上一版一致。**电脑端新增的多格式照片写入（DNG/JPG/JPEG/PNG/HEIC/HEIF，见上级完整维护文档8.7节）同样与手机端无关**：照片补录页整页只在电脑端显示，本端既不识别也不写入这些格式，`shared/ui/app.js`里那份`PHOTO_RE`只是双端共用的界面代码，手机端上它不参与任何路径。

**本版Android侧的改动只有版本码/版本名递增**（`android/app/build.gradle.kts`：`versionCode = 13`、`versionName = "1.5.1"`，1.5.0是`12`/`1.5.0`；`android-build-verification.txt`独立核对），多格式与本端无关。

构建脚本在assembleRelease前会把`../shared/ui/*`同步到`app/src/main/assets/ui`，界面只改shared/ui即可；同步后的assets副本随源码归档，需与shared/ui逐字节一致。

## 超级岛相关组件

- `XiaomiIsland.java`：能力三态探测、`param_v2`组装、诊断与测试通知。任何异常只记录不外抛，普通前台通知与定位不受影响。
- `IslandActionReceiver.java`：岛上“停止”按钮入口。小米官方模板库要求`actionIntent`指向的组件声明`exported="true"`，故该接收器导出；它只接受`app.nefgpstrack.ISLAND_STOP`、不读参数、不返回数据，且仅在记录进行中才转发停止请求。
- 资源：`ic_island_route.xml`、`ic_island_route_dark.xml`（深浅两套岛图标）、`ic_island_function.xml`（功能图标）、`ic_island_stop.xml`（动作按钮图标）。JSON里的键必须是`miui.focus.pic_`前缀，且同名资源要放进`miui.focus.pics`。
- 记录通知渠道为`tracking_status`（IMPORTANCE_LOW），测试通知渠道为`island_test`。渠道重要度在设置页诊断里显示。
