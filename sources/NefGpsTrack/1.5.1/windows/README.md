# Windows途记1.5.1

构建、路径库、WebView2、CLP、照片写入（NEF/DNG/JPG/JPEG/PNG/HEIC/HEIF，见完整维护文档8.7节）、就地改写、拖入导入、多轨迹择优、曲线分工、四维海拔、匹配地图、安装器、数据布局、自检和备份见上级完整维护文档.md（第4节数据布局、第5节安装器与命令行、第9.9节照片页版式）。当前交付及文本证据位于D:\Codex\途记专项\outputs\NefGpsTrack\1.5.1。

EXE窗口标题为`途记 1.5.1 · NEF GPS Studio`，界面嵌入`../shared/ui`同一份文件，与Android端视觉一致。窗口背景色`#f3f8ff`需与style.css的`--bg`保持一致。

## 交付形态与安装（本版改动）

- 用户拿到的交付件是**安装器**`NefGpsTrack-Setup-1.5.1.exe`（48,827,379字节），自研，界面是`installer/ui/index.html`，逻辑在`installer/core.py`（纯逻辑、无界面）+`installer/app.py`（pywebview）。主程序EXE以`payload/途记.exe`内嵌，与同时保留的便携主程序`NefGpsTrack-Windows-1.5.1.exe`（31,500,225字节）**逐字节一致**（`qa/package-check.py`比对SHA256）。
- 安装判定读`HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\NefGpsTrack`的`InstallLocation`：**已装且目录存在**走升级模式，显示原位置与版本、只给「开始升级」、**不询问路径**、按原路径覆盖且`data\`一字不动；**未装**（或卸载项还在但目录已消失）走全新安装，默认`%LOCALAPPDATA%\Programs\途记`并可改选。可写性用真实写探测（`installer/core.py::check_writable`），不可写就禁用安装按钮。**安装器与本程序都不提权**。
- 便捷对照：便携主程序`NefGpsTrack-Windows-1.5.1.exe`在没有安装信息时，数据根就是**EXE同级的`data\`**（`paths.data_root()`的第2级），所以它是“绿色版”用法；装出来的`<安装路径>\途记.exe`同规则，数据在安装目录下的`data\`。

## 数据位置（本版改动）

```
<安装路径>\data\路径库\       用户可能要用的：每条轨迹一个可读文件名的 .clp，另有 导出\
<安装路径>\data\程序数据\     仅供程序读的：settings.json、安装信息.json、日志\
```

- 数据根优先级（`paths.py`）：`--data-dir` / `NEFGPSTRACK_DATA` → 打包时EXE所在目录的`data` → 源码运行时仓库根的`data`。`library.py`不自己读环境变量，默认就是`paths.routes_dir()`。
- 轨迹标识就是**可读文件名去掉扩展名**（`library.readable_stem()`，形如`2026-09-24_1355_连续_115点`，重名加`_2`）；`library.safe_stem()`拒绝任何路径分隔符与`..`，并校验解析后仍在路径库目录内。
- 旧版遗留的32位十六进制文件名由主程序启动时按内容改成可读名（`Library.migrate_readable_names()`，`app.py`主入口调一次）；解不开的文件原样留在原地。安装器侧的迁移只做纯文件复制，见完整维护文档4.2节。

## 卸载

注册表`UninstallString`是`"<安装路径>\途记.exe" --uninstall`：原生确认框问两次（是否卸载 / 是否一并删除数据），删注册表项与快捷方式；选择保留数据时`data\`原样留着；安装目录由一个脱离的`cmd`在本进程退出后清理。加`--silent`跳过确认框并保留数据。实现见`app.py::_run_uninstall()`。

## 第二步曲线（含本版新增的四维海拔）

手机端1.4.2起只做第一步（滤除GPS漂移，结果就是CLP里的`points`），**第二步「插值形成平滑曲线」由本端在选中CLP时完成**：

- `smoothing.py::build_curves()`是第二步入口（旧名`smooth_payload`保留为别名），职责注释与函数名都以“第二步”为准。读到任何载荷都**先剥掉`curve`再按`points`重建**，不信任外来系数；对`smoothing`已是`robust-stop-v1/v2`的载荷只插值、不重复平滑。
- **海拔本版也被平滑**：`smoothing.smooth_altitude()`对海拔轴做鲁棒IRLS（二阶差分粗糙度惩罚，σ由二阶差分中位数估计并夹在1.0—30.0米），结果写回`points[i]['alt']`，载荷加`altitudeSmoothing='robust-alt-v1'`，`rawPoints`里的原始海拔不动；已知海拔少于三个时原样返回。**σ必须用二阶差分**：一阶差分里混着真实坡度，会把爬升当噪声、导致平滑不足。
- **曲线新增`alt`子曲线**：`curve.py::build_curve()`只以海拔已知的结点为节点建这条子曲线，`evaluate()`的海拔改查它，于是中间缺失海拔的时段由前后已知海拔跨过去插值；首末已知海拔之外与轨迹范围外仍返回`None`（不臆造），整条无海拔时恒为`None`。可用范围由`curve.py::altitude_span()`给出。`curve.py::VERSION`因此升为`pchip-4d-v2`。
- 路径库读CLP走`library.py::_decode()` →`smooth_payload()`，因此加载后的载荷一定带本端重建的`curve`；照片匹配另由`time_match.build_track_index()`按同一批节点建索引。
- `smoothing.py::_fit`是第一步的Python等价实现，**只给`smoothing`缺失或无法识别的旧CLP兜底**（这类文件没有第一步结果，只能补做），不要扩用成常规路径；它本版**逐字节未改**，与Java的数值一致性由`qa/test_v120.py::test_whole_route_horizontal_java_parity`守护。
- `curve.py::build_curve`仍是唯一的曲线实现。

## 桌面端专属行为

- **原生拖放**：页面加载后由`window.events.loaded`注册`body`的 drop 处理器（`DOMEventHandler(api.on_native_drop)`），把`pywebviewFullPath`交回界面；成功后设`window.__nativeDropReady=true`，界面自己的 drop 处理随即让位。注册失败时`api.native_drop=False`，界面退回`.clp`字节通道。
- **照片格式（本版新增）**：受支持的7个后缀由`exiftool_io.py::SUPPORTED_SUFFIXES`唯一定义，`is_supported_photo()`判断后缀、`file_type_ok()`校验扩展名与 ExifTool 报出的`FileType`是否自洽（不符时跳过原因写“扩展名与文件内容不符（读到 X）”，空`FileType`判为不通过）。**写入链路对四种容器通用，不按格式分支**：NEF/DNG（TIFF系）、JPG/JPEG、PNG（`eXIf`块）、HEIC/HEIF（BMFF容器）的 GPS 标签都落在`GPS:`组，所以`write_gps()`/`verify_gps()`/`clear_gps()`同一套参数即可；唯一按格式取值的地方是`FILE_TYPES`。`batch.py::scan_photos()`（原`scan_nefs()`）扫目录、`collect_photos()`收文件清单，两者都按受支持后缀过滤；`_stage_photo()`的隐藏临时副本**保留原扩展名**（`.<名字>.clp-<uuid><原后缀>`），此前硬写`.NEF`对 PNG/HEIC 会失败。界面侧的清单镜像在`shared/ui/app.js::PHOTO_RE`。逐格式回归见`qa/test_formats.py`（8项，夹具`qa/formats/`为合成件）。
- **照片集**：`Api.photos`持有待处理**照片**（受支持格式）的绝对路径；`photos-add`、`photos-pick`、`photos-clear`维护它。照片清单一律以桌面端为准，界面不回传路径，避免上百条路径来回过桥；预览时把快照存进`plan_photos`，写入前比对，清单变了就要求重新预览。
- **已有定位的判定**：`prepare_plan()`用`ExifTool.has_existing_position()`（只看`GPS:GPSLatitude`/`GPS:GPSLongitude`/`GPS:GPSAltitude`有没有非空值）决定队列，`has_existing_gps()`（有没有任何`GPS:`标签）只用来区分“空GPS IFD”这种可写情形；判定结果落进`PlanRow.existing_position`与`has_gps_ifd`。未勾选覆盖时真有经纬度海拔的照片一律跳过、原片不动；勾选覆盖时`_stage_photo()`先在临时副本上`clear_gps()`再写并读回验证，副本上若发现未获准覆盖的已有定位则抛错、清理临时文件、不动原片。
- **匹配地图的数据**：`_preview()`除`rows`外还给出`points`（`status=='ready'`且有匹配的照片：`n`/`relative`/`lat`/`lon`/`alt`/`method`/`track`）与`tracks`（`batch.track_lines()`把本次使用的曲线转成`[lat, lon]`折线，单条最多4000点、合计不超过12000点，超出等间隔抽稀、保留时间序）。`PlanRow.number`是照片在本次预览里的编号（从1起），`rows[0]`、`points[].n`与写入后的`written[].n`三处编号必须一致。
- **多轨迹**：`preview`/`write`的`tracks`是被勾选的轨迹 id 列表，`trackLabels`是界面给的显示名。择优规则在`batch.pick_track()`。
- **合并模式**：界面分段控件`#track-mode`把`prefs.trackMode`（`separate`默认／`merge`）经`mergeTracks`参数传进来，落到`Options.merge_tracks`；为真时`batch.load_tracks()`不再逐条建索引，改为调`batch.merge_sources()`把`mode=track`的CLP按首节点时刻升序串成一条曲线（单点被排除并提示，同一`t`保留`hacc`更小者，合并后不足两点报错），预览状态栏显示“合并为一条曲线”。段间空档不特殊处理，仍按`MAX_INTERPOLATION_GAP_MS=120000`判长间隔估算。切换后属`signature`变化，必须重新预览。
- **不生成表格文件**：`batch.py`无审计 CSV，`execute_plan`只返回逐张结果元组。
- **写入方式**：`Options.in_place`控制。副本模式下`output`是输出目录；就地模式下`output`是可选的备份目录，可为`None`。
- **偏好**：`app.py`的`Prefs`读写`paths.settings_file()`，即`data\程序数据\settings.json`（同目录若只有旧名`prefs.json`会兜底读一次），当前键为`writeInPlace`、`defaultOffset`与`trackMode`。
- **写入结果预览**：`job.written`逐张给出`n`/`relative`/`track`/`lat`/`lon`/`alt`/`method`/`captureUtc`；处理表格与写入结果表格都以`#`序号开头。
- **查看页提示条**：`#curve-note`在载荷带`curve`（即经本端第二步生成）时显示“平滑曲线 pchip-4d-v2：电脑端按这 N 个节点生成，节点之间为曲线”并加`live`样式（版本号取自`curve.version`，不写死）；界面`curvePosition()`此时用Hermite公式求值，没有`curve`时退化为两点直连。
- **照片页匹配地图**：`#photo-map-panel`/`#photo-map`由界面侧`renderPhotoMap()`绘制（折线+带编号的`div.photo-pin`），数据全部来自`job.points`/`job.tracks`；桌面端才有，手机端永远隐藏。面板在电脑端**常显**：没有可画的数据时只显示占位提示`#photo-map-empty`，地图实例懒初始化（占位阶段不建`L.map`、不加载瓦片），有图钉或轨迹时才建图。桌面端不参与图钉的落点计算，编号与坐标必须由`_preview()`给准。
- **照片页版面**：`.photo-grid`的直接子元素是左列表单与右列容器`.photo-side`；`photo-side`内纵向堆叠「处理进度」与「匹配位置」，两者等宽同列。「写入照片副本」`#write`由界面文档移到匹配位置面板内、地图**下方**，判定条件不变（电脑端 && 非忙 && 预览就绪）；`#preview`/`#cancel-job`留在左列表单的`.actions.stacked`里。几何关系由`qa/ui-151.cjs`断言，细节见完整维护文档9.9节。

## 验证入口

合并模式的数值规则、`build_curves()`的重建行为、四维海拔与空GPS IFD的判定由`windows/qa_windows.py`（**32项**，含合并模式6项、图钉用折线与编号，以及本版新增的「every supported format writes, verifies and clears」）与`qa/test_v120.py`（20项，含海拔轴平滑、已有定位判定与数据层5项）覆盖；**多格式写入由`qa/test_formats.py`（8项，夹具在`qa/formats/`）覆盖**；界面侧由`qa/ui-151.cjs`（**134项**，含编号、图钉、`stacked`按钮、照片页12项版面断言与多格式分流断言）覆盖；安装器的检测、可写性、安装、升级保数据、迁移幂等与卸载项由`qa/test_installer.py`（17项，全部走临时目录与临时注册表根）覆盖。各份记录的本地位置与边界见`qa/本版验证索引.md`，实机人工项见`qa/device_acceptance.md`。

## 自检

`--self-check`带样片时会依次做副本写入、就地改写、多轨迹择优（档位与范围外回退）、“未生成表格文件”、`empty GPS IFD is writable`、`4D curve supplies an altitude`，以及本版新增的**`data folder and readable route name`**（`Library()`根必须是`routes_dir()`、`routes_dir()`必须在`data_root()`下、导入一条探针轨迹后文件名含「连续」与「1点」，随后删掉探针）；`--ui-check`会核对拖入层、照片列表、轨迹多选器、`window.__nativeDropReady`、设置入口与卡片、写入结果预览与写入方式控件、`#track-mode`、`#curve-note`、`#photo-map`（记录字段`ui.photoMap`）与`openRoute`/`renderTrack`后的节点计数文本（记录里的`ui.trackMode`、`ui.curveNote`、`ui.photoMap`必须都为真，`ok`才算过）。`--data-dir <路径>`覆盖数据根，必须在其余参数之前解析——`app.py`入口先摘出它，其余分支只读`argv_rest`派生的变量；报告写入包在`try/finally`里，保证写完与否都会`window.destroy()`（此前按下标读`sys.argv`曾导致界面检查挂死，勿回退）。
