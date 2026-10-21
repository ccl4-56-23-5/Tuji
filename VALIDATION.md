# 公开发布验证 · 2026-10-21

本次检查针对 1.5.1 的公开源码副本。轨迹算法和界面代码与原归档逐字节一致；口令读取入口与 Android 构建注入配置作了公开化调整，原固定口令不再出现在公开源码中。现有 Android APK 与 Windows EXE 没有重新编译。

| 检查 | 结果 |
| --- | --- |
| 核心逻辑 `qa/test_v120.py` | 20 项，19 通过，真实 NEF 样片检查跳过 1 项 |
| 安装器 `qa/test_installer.py` | 17 项通过 |
| 多格式 `qa/test_formats.py` | 8 项通过；使用合成 DNG/JPG/PNG/HEIC 夹具与 ExifTool 13.59 |
| 公共协议向量 `qa/verify_clp1_vector.py` | 派生密钥、加密、解密、错误口令、AAD 和密文检查通过 |
| 模拟桥接界面 `qa/ui-151.cjs` | 合成轨迹下 134 项通过，JavaScript 错误 0 条 |
| 安装文件完整性 | APK、安装器与便携 EXE 的 SHA-256 均与原归档 SHA256.txt 一致 |
| 公开目录检查 | 排除发行签名材料、私有轨迹与原 QA 截图；替换真实轨迹夹具及位置常量 |

浏览器检查使用 Microsoft Edge 与 Playwright，通过模拟桥接验证界面行为。安装器测试在临时目录与临时注册表根执行。上述结果不代表 Android 真机录制、后台存活、超级岛、真实相机照片兼容性或完整安装升级卸载的人工验收。

后续人工项目见 [设备验收清单](sources/NefGpsTrack/1.5.1/qa/device_acceptance.md)。下载完整性见 Release 中的 SHA256SUMS.txt。

## 图文与口令配置更新

- 使用新的测试专用口令重跑核心逻辑 20 项（通过 19 项，真实 NEF 项跳过），多格式 8 项通过。
- Python 公共协议向量通过；修改口令读取后的 Java 实现也通过相同 UTF-8/PBKDF2/AES-GCM 向量。
- Android 在项目内临时 ASCII 映射路径完成 `:app:generateReleaseBuildConfig --offline --no-daemon`，验证本地测试口令注入。未重新编译或替换发行 APK。
- 新截图脚本在合成数据下完成 134 项界面断言，JavaScript 错误 0 条。手机回看截图重新加载手机载荷，电脑截图以视口方式取景，避免全页截图中的固定页头错位。
- 合成 PCHIP 数值例子直接调用 curve.py，25 秒处结果 `11.548780487804878`；海拔子曲线的两端未知范围另有断言。
- 用户授权的真实记录用未修改的 Java TrackSmoother 复算，输出与 CLP 已存去漂移节点一致。公开只保留移除地理定位信息的 PNG 对比；无地面真值，不作为绝对精度验收。
- 实际配置文件忽略规则与公开源码扫描在上传前核对；保留的原 1.5.1 APK/EXE 仍有原固定互通行为，不作密码系统已升级的声明。
