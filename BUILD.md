# 构建途记 1.5.1

建议在 Windows PowerShell 中执行；源码路径包含中文时，Android 构建入口会临时映射 ASCII 盘符，缓存实际保存在仓库的 temp/ 中。所有 .ps1 保持 UTF-8 BOM。

## 先配置本机 CLP 互通口令

公开源码不包含原发行版的固定口令。Android、Windows 必须使用相同配置才能互读新生成的 CLP；随意更换口令不能解密已有文件。需要读取旧 CLP 时，应由文件所有者在本机提供兼容口令。

- Windows：复制 `windows/clp_secret.example.py` 为同目录 `clp_secret.py`，在本机填写 `CLP_PASSWORD`；或在运行时设置 `NEFGPSTRACK_CLP_PASSWORD` 环境变量。配置模块会优先于环境变量。打包需要内嵌本机配置时，在构建前准备好该文件。
- Android：复制 `android/clp-private.properties.example` 为同目录 `clp-private.properties`，填写 `clpPassword`；也可用 `NEFGPSTRACK_CLP_PASSWORD` 环境变量或 Gradle 属性 `tujiClpPassword` 注入。构建会生成 `BuildConfig.CLP_PASSWORD`。
- 两个实际配置文件均已加入 `.gitignore`，不要提交。公共协议测试向量中的测试密码为虚构向量的一部分，与原发行口令无关。

这只是从公开源码中移除固定口令，不等于编译后的程序具有不可提取的密钥存储。现有 APK/EXE 保留原互通行为；本次未改造成用户交互式密码系统。

## Windows

需要 Python 3.12 或兼容版本、WebView2 Runtime；依赖版本见 windows/requirements-build.txt。构建脚本会创建独立虚拟环境并使用源码附带的 ExifTool 13.59 分发包。

```powershell
$repo = (Get-Location).Path
& .\sources\NefGpsTrack\1.5.1\windows\build-windows.ps1 `
  -Python 'C:\Python312\python.exe' `
  -BuildRoot (Join-Path $repo 'temp\windows-1.5.1') `
  -OutputDirectory (Join-Path $repo 'outputs\NefGpsTrack\1.5.1')
```

输出目录须不含同名交付文件。源码运行可安装运行依赖后执行 windows/app.py；完整说明见 windows/README.md。

## Android

需要 JDK 17、Android SDK（build-tools 36.0.0，以及 app/build.gradle.kts 声明的 compileSdk），Gradle Wrapper 已包含。

不需要发行签名时，可在 android/ 目录执行 `gradlew.bat :app:assembleDebug`，自行设置 JAVA_HOME、ANDROID_HOME 和位于仓库 temp/ 下的 GRADLE_USER_HOME。中文路径下建议先将工程及 shared/ui 复制到项目 temp/ 中的 ASCII 映射路径。

发行脚本通过 -ToolRoot 指定本机工具目录，预期结构：android-sdk/、jdk-17.0.10.7-hotspot/、signing/nefgpstrack/release.p12 与 release-secret.json。后者由构建者在本机提供 alias、password 两个字段。仓库不包含原作者签名材料；自行签名的 APK 不能覆盖原签名安装。

```powershell
$repo = (Get-Location).Path
& .\build-android.ps1 -Version 1.5.1 `
  -ToolRoot 'C:\AndroidTools' `
  -BuildCacheRoot (Join-Path $repo 'temp\NefGpsTrackBuilds') `
  -GradleUserHome (Join-Path $repo 'temp\gradle-cache')
```

## 检查

```powershell
python .\sources\NefGpsTrack\1.5.1\qa\test_v120.py
python .\sources\NefGpsTrack\1.5.1\qa\test_installer.py
python .\sources\NefGpsTrack\1.5.1\qa\verify_clp1_vector.py
$env:NEFGPSTRACK_EXIFTOOL = 'C:\Tools\ExifTool\exiftool.exe'
python .\sources\NefGpsTrack\1.5.1\qa\test_formats.py
```

ui-151.cjs 需要 Node.js、Playwright 与 Microsoft Edge。运行后生成的截图与验证 JSON 默认忽略，不纳入源码归档。
