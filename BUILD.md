# 构建途记 1.5.2

## 配置 CLP 互通口令

Android 和 Windows 从源码构建时使用同一口令。读取现有 CLP 时，由文件所有者在本机提供兼容口令。

- Android 可设置 NEFGPSTRACK_CLP_PASSWORD 环境变量、Gradle 属性 tujiClpPassword，或复制 android/clp-private.properties.example 为 android/clp-private.properties 并配置 clpPassword。
- Windows 可设置同一环境变量，或复制 windows/clp_secret.example.py 为 windows/clp_secret.py 并配置 CLP_PASSWORD。本地模块优先，打包时可内嵌该模块。

## Android

安装 JDK 17、Android SDK Platform 37 和 Build Tools 37.0.0，设置 JAVA_HOME、ANDROID_HOME。Windows 建议将仓库克隆到纯 ASCII 路径。项目包含 Gradle Wrapper。

从仓库根目录运行 `.\build-android.ps1`，默认完成 Release 构建、Lint 和本地测试。未签名的 APK 位于 Android 工程的 app/build/outputs/apk/release。用 SDK 的 zipalign 和 apksigner 及自己的发行证书签名。已有途记用户请用 Release 附带的原签名 APK 覆盖安装。

## Windows

安装 Python 3.12 和 WebView2 Runtime。在仓库根目录执行：

```powershell
& .\sources\NefGpsTrack\1.5.2\windows\build-windows.ps1 -Python 'C:\Python312\python.exe'
```

脚本使用 requirements-build.txt 和附带的 ExifTool 13.59。默认安装器与便携主程序输出到 outputs/NefGpsTrack/1.5.2。可提供 -BuildRoot 与 -OutputDirectory 自行指定位置。Windows 安装器首次可选安装路径，覆盖升级沿用已登记路径。

## 核验

qa 中包含 Python 算法、照片格式、安装器逻辑和 CLP 协议向量回归。运行 test_formats.py 时以 NEFGPSTRACK_EXIFTOOL 指定现有 ExifTool。UI 检查需要 Node.js、Playwright 和 Microsoft Edge。发布安装包的检查结果见 [VALIDATION.md](VALIDATION.md)。
