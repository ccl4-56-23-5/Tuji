# 图片来源与公开范围

## 界面截图

2026-10-21 从未修改的 1.5.1 HTML、CSS 与 JavaScript 渲染，使用 Microsoft Edge 和 Playwright。手机视口为 390 × 844；电脑视口为 1440 × 1400。轨迹、照片名和桥接结果全部使用公开 QA 的合成数据；在线地图瓦片请求关闭。

这些截图展示实际界面代码，不是 Android 真机、Windows EXE 或真实照片写入的验收证据。手机回看截图会重新加载不含电脑曲线的手机载荷，避免展示跨平台测试留下的曲线提示。

| 图片 | 内容 |
| --- | --- |
| images/android-recording.png | 手机记录状态 |
| images/android-library.png | 手机路径库 |
| images/android-review.png | 手机节点回看 |
| images/windows-matching.png | 照片匹配预览与编号图钉 |
| images/windows-results.png | 合成的写入结果 |
| images/windows-settings.png | 电脑设置 |
| images/windows-library.png | 电脑路径库 |

在安装 Node.js、Playwright 和 Microsoft Edge 的环境中，从仓库根目录执行 `node docs/capture-screenshots.cjs` 重新生成。脚本复用公开 QA 的断言与模拟桥接，取图输出到 docs/images，临时测试产物留在 temp。

## 算法示意图

interpolation-demo.png 和 altitude-demo.png 使用完全虚构的数据，直接调用仓库的 curve.py。重现脚本是 render-algorithm-demos.py；不需要真实 CLP 或原发行口令。

## 真实记录的匿名化对比

drift-comparison.png 和 drift-detail.png 来自用户授权展示的记录，从第 70 个点开始截取，先对完整记录执行现有去漂移算法。原始与处理后路径采用同一平移、旋转与统一缩放变换。图片没有地图、经纬度、地理原点、朝向、时间或距离刻度。

真实记录只公开上述 PNG；不上传原始 CLP、解密 JSON、逐点表、数值轨迹、变换参数或真实地点信息。图片仍包含用户明确授权展示的路径形状，不代表可以消除所有基于形状识别的可能性。
