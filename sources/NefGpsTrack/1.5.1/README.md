# 途记1.5.1

**本版是安装式发布**：交付件从便携EXE改成安装器`NefGpsTrack-Setup-1.5.1.exe`，程序与本地数据一起装到用户选定的安装路径下，升级不再询问路径、数据原地不动。安装之外，界面层还重构了照片补录页的版面（匹配位置面板与写入按钮换位置），并补了旧数据迁移、可读轨迹文件名等一整套数据落位规则。**电脑端照片补录也从只支持 NEF 扩展到 NEF / DNG / JPG / JPEG / PNG / HEIC / HEIF**（第4节）。前几版已完成的四维平滑、空GPS IFD判定、照片编号与图钉不变。

源码：`D:\Codex\途记专项\sources\NefGpsTrack\1.5.1`；交付：`D:\Codex\途记专项\outputs\NefGpsTrack\1.5.1`。Android版本名1.5.1、版本码13，包名`app.nefgpstrack`与签名沿用前版，可覆盖升级。

## 1. 安装式发布：装器、装到哪、怎么升级

- 交付件是**自研安装器**`NefGpsTrack-Setup-1.5.1.exe`（48,827,379字节），不依赖 Inno Setup / NSIS。它由`installer/core.py`（纯逻辑，无界面）+`installer/app.py`（pywebview界面）+`installer/ui/index.html`组成，主程序EXE作为载荷内嵌，与独立保留的便携主程序`NefGpsTrack-Windows-1.5.1.exe`（31,500,225字节）**逐字节一致**（`qa/package-check.py`按SHA256断言）。
- **启动先判定是否已装**：读注册表`HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\NefGpsTrack`的`InstallLocation`。
  - **已安装且目录存在** → **升级模式**：显示原安装位置与原版本，只给「开始升级」，**不询问路径**，直接按原路径覆盖程序，`data\`一字不动。
  - **未安装**（或卸载项还在但目录已消失）→ **全新安装**：默认`%LOCALAPPDATA%\Programs\途记`，可「浏览」改选。
- **可写性检查是真实写探测**（建临时文件再删）：不可写就禁用安装按钮并说明原因，另给「用默认位置」。`C:\Program Files`与`C:\Windows\System32`在普通用户下实测被拒绝，所以默认位置选在免提权的用户目录，**安装器与主程序都不提权**。
- 安装步骤逐步显示进度：检查位置 → 准备数据目录 → 检查程序是否在运行 → 写入程序文件（先写`.new`再原子替换）→ 记录安装信息 → 登记卸载项 → 创建开始菜单快捷方式 → （可选）迁移旧数据。
- 注册表卸载项写`DisplayName`/`DisplayVersion`/`Publisher`/`DisplayIcon`/`InstallLocation`/`UninstallString`（`"<路径>\途记.exe" --uninstall`）/`QuietUninstallString`/`NoModify`/`NoRepair`/`EstimatedSize`，并创建`%APPDATA%\...\Start Menu\Programs\途记.lnk`。
- 无人值守入口：`--probe`、`--silent-install <目录>`、`--silent-upgrade`、`--no-migrate`；测试用`--reg-root`与`--shortcut`可改写到临时注册表根与临时快捷方式位置。
- **卸载**由主程序`--uninstall`执行：原生确认框问两次（是否卸载 / 是否一并删除数据），删注册表项与快捷方式；选择保留数据时`data\`原样留着；最后交给一个脱离的`cmd`在本进程退出后清理安装目录。

## 2. 数据入安装路径：两个文件夹、可读文件名、自动迁移

```
<安装路径>\
  途记.exe
  data\
    路径库\                   用户可能要用的：每条轨迹一个可读文件名的 .clp
      2026-09-24_1355_连续_115点.clp
      导出\
    程序数据\                  仅供程序读的
      settings.json           界面偏好（原 prefs.json）
      安装信息.json
      日志\
```

- **数据根解析优先级**（`windows/paths.py`）：`--data-dir` / 环境变量`NEFGPSTRACK_DATA` → 打包时主程序EXE所在目录的`data` → 源码运行时仓库根的`data`。`library.py`不自己读环境变量，默认就是`paths.routes_dir()`。
- **可读文件名**：导入后按内容命名`<日期>_<时分>_<模式>_<点数>点.clp`（`mode=single`写「单点」），重名追加`_2`、`_3`；界面与进程之间传的轨迹标识就是文件名去掉扩展名，不再用32位十六进制。`library.safe_stem()`拒绝任何路径分隔符与`..`，并校验解析后仍在路径库目录内。
- **旧数据自动迁移**：安装时发现`%LOCALAPPDATA%\NefGpsTrack`就把`routes\*.clp`复制到`data\路径库\`、`prefs.json`复制成`data\程序数据\settings.json`；**原目录整份保留不删**，迁移可重复执行且从不覆盖已有文件。安装器只做纯文件复制（不带`cryptography`），旧版遗留的32位十六进制文件名由**主程序首次启动时**按内容改成可读名（`Library.migrate_readable_names()`，解不开的文件原样留在原地）。
- 用户可见的`路径库`与只给程序读的`程序数据`分开，是为了让“我要拷走的轨迹”和“程序自己的状态”互不混淆；两个文件夹都由`paths.ensure()`按需创建，**已存在的一律不清空**。

## 3. 照片补录页的新版面：右列两个面板、写入按钮在地图下方

- `.photo-grid`变为两个直接子元素：**左列表单 + 右列容器`.photo-side`**。右列里纵向堆叠「处理进度」与「匹配位置」两个面板，**同宽同列**；包这层容器是为了让进度框贴合自身内容，不被左侧长表单拉伸出一大块空白。
- **「写入照片副本」按钮从表单移出**，放在「匹配位置」面板内、地图**下方**，撑满内容区；「预览匹配」与「停止处理」留在左列表单。
- **匹配位置面板在电脑端常显**：没有预览结果时显示占位提示「预览匹配后，这里按编号显示每张照片的位置」，地图**懒初始化**（占位阶段不建实例、不加载瓦片）；手机端整个隐藏。
- UI优化：面板圆角/内边距/标题层级统一；地图高度360 / 窄屏（≤980px）300 / 手机（≤720px）280；**`>980px`才分两列**，980与860回落单列且顺序为表单→处理进度→匹配位置。
- 编号列、带编号图钉与行↔图钉双向联动的规则不变（见完整维护文档9.9节）。

## 4. 照片格式（本版新增）

- **支持7个后缀**：`windows/exiftool_io.py::SUPPORTED_SUFFIXES = ('.nef','.dng','.jpg','.jpeg','.png','.heic','.heif')`，是唯一来源；界面`shared/ui/app.js`的`PHOTO_RE`与`PHOTO_LABEL`是它的镜像。改了要同时改两端，否则`qa/package-check.py`失败。
- **写入逻辑天然通用，不按格式分支**：用 ExifTool 13.59 实测，NEF/DNG（TIFF系）、JPG/JPEG、PNG（`eXIf`块）、HEIC/HEIF（BMFF容器）的 GPS 标签**都落在同一个`GPS:`组**，所以`-GPS:GPSLatitude`这类参数、读回与`-GPS:all=`清理对四种容器都成立。**不要改成「按格式分别处理标签组」**。唯一按格式取值的是`FILE_TYPES`（扩展名 → ExifTool `FileType`），用于自洽校验。
- **新增`is_supported_photo()`与`file_type_ok()`**：前者判断后缀是否受理，后者校验扩展名与文件内容是否自洽；不符时跳过原因写「扩展名与文件内容不符（读到 X）」。`clear_gps()`/`write_gps()`的入口守卫从写死的`.nef`换成`_require_supported()`。
- **临时副本保留原扩展名**：`batch.py::_stage_photo()`用`.<名字>.clp-<uuid><原后缀>`，原先硬写`.NEF`，对 PNG/HEIC 会失败。`scan_nefs()`改名`scan_photos()`，目录与文件清单都按受支持后缀。
- **界面口径**：标题为「途记 · 照片 GPS」，照片页说明、投放层提示、就地改写警告里的「NEF」都改成「照片」；「选择照片」的过滤器是`照片 (*.nef;*.dng;*.jpg;*.jpeg;*.png;*.heic;*.heif)`。
- **夹具是合成的**：`qa/formats/`下`shot.dng`/`shot.jpg`/`shot.png`/`shot.heic`由 tifffile + Pillow + pillow-heif 生成，不含真实拍摄内容；测试只读、只操作临时副本。
- **尚未验收**：真机 DNG 与手机 HEIC 没试过；写入后 PNG 新增的`eXIf`块是否被第三方看图软件识别没实测过。详见第6节。

## 5. 沿用前版的行为

- 曲线生成两步分工：手机端`TrackSmoother.java`只做第一步（`smoothing=robust-stop-v2`），电脑端`curve.py::build_curve`做第二步（`curve.version=pchip-4d-v2`，含海拔子曲线）；海拔平滑`smooth_altitude()`在电脑端，载荷标`altitudeSmoothing='robust-alt-v1'`。
- 照片补录三步：`01 选择轨迹` → `02 导入照片` → `03 预览并写入`；曲线生成方式仍可选`各自成曲线`（默认）/`合并为一条`，存在`settings.json`的`trackMode`。
- 已有定位只按经纬度海拔判定（`ExifTool.has_existing_position()`），空GPS IFD不再拦截；未勾选覆盖时真有经纬度海拔的照片跳过且原片哈希不变。
- 写入不生成任何表格文件；写入方式仍可在设置页切换「新建副本 / 覆盖原始文件」。
- 手机端本版未改动。

## 6. 验证

- 界面回归`qa/ui-151.cjs`共**134项**断言，本地记录`qa/ui-151-verification.json`为`ok: true`、0条JavaScript错误。其中交付前为照片页版面补了12项几何与懒初始化断言（网格两个子元素、右列恰好两个面板、两面板等宽同列、地图面板在进度面板下方、进度面板没被拉伸、`#write`在地图下方且面板内、`#preview`在左列、电脑端预览前不隐藏面板并显示占位、预览前不创建地图实例）；**本版又补了多格式分流断言**：拖入`.dng`/`.jpg`/`.png`/`.heic`/`.heif` 全部按照片受理、`.tif`/`.bmp` 被跳过（`ui-151.cjs`第319—323行）。
- 桌面集成`windows/qa_windows.py`共**32项**检查，覆盖空GPS IFD不再拦截、跳过原因与`existing_position`/`has_gps_ifd`标记、预览行编号、合并预览的编号与折线、折线抽稀上限，以及**新增的「every supported format writes, verifies and clears」**（`qa/formats/`每种受支持格式走一遍写入→读回→清理，夹具不得被写脏）。
- **多格式回归`qa/test_formats.py`共8项**（本版新增）：后缀清单与文档一致、`FILE_TYPES`自洽、每个夹具的`FileType`符合预期、逐格式写入→读回→清理、有定位时覆盖替换旧值且不并存、海拔未知时都不写海拔、非受支持后缀被拒、夹具未被写脏。
- 核心回归`qa/test_v120.py`共**20项**，交付前新增数据根解析、可读文件名与重名、路径穿越拒绝、导入落位到数据目录、旧十六进制名改造五项。
- 安装器回归`qa/test_installer.py`共**17项**，覆盖检测、可写性、安装、升级保数据、迁移幂等、卸载项；全部用临时目录与临时注册表根，不碰真实卸载项与开始菜单。
- 打包EXE自检新增`data folder and readable route name`；`--ui-check`契约新增`photoMap`标记。`qa/package-check.py`新增断言：安装器内嵌载荷与独立主程序**逐字节一致**、数据布局常量未变、`library.py`不自己读环境变量；**多格式**另有四组——后端7个后缀字面量齐全、含`file_type_ok`与`SUPPORTED_SUFFIXES`、界面含`PHOTO_RE`与`heic`/`dng`、夹具不少于4个。

尚未验收：**多格式的三条**——`qa/formats/`夹具是合成的（真机 DNG 与手机 HEIC 未试）、写入后 PNG 新增的`eXIf`块是否被第三方看图软件识别未实测；安装式发布的四条人工项（自定义路径全新安装、二次运行不询问路径且数据不动、假旧目录迁移、卸载保留数据）与照片页版面的实机观感，见`qa/device_acceptance.md`；此外真实鼠标拖放手势（回归用合成事件）、就地改写后原片在Nikon软件里的识别、图钉联动的实机手感仍未验收。

完整维护说明见[完整维护文档](完整维护文档.md)：第7节写CLP协议与四维曲线，第4节写数据布局、可读文件名与迁移，第5节写安装器与安装/升级/卸载流程及命令行参数，第8.6节写“什么才算已有定位”，第8.7节写支持的格式清单与“写入逻辑为何不需要按格式分支”，第9.9节写照片页版式与按钮位置，第13节故障排查含“安装器说位置不可写”“升级后找不到旧轨迹”“装了新版但路径库是空的”“界面检查挂死”“扩展名与文件内容不符”等条目。
