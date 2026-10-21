"""本地数据目录解析。

1.5.0 起所有本地数据都放在**安装路径**下的 `data\\`，不再写 `%LOCALAPPDATA%`：

```
<安装路径>\\data\\
  路径库\\            用户可能要用的：每条轨迹一个可读文件名的 .clp，另有 导出\\
  程序数据\\          仅供程序读的：settings.json、安装信息.json、日志\\
```

目录解析优先级：
1. 显式覆盖：命令行 `--data-dir` 或环境变量 `NEFGPSTRACK_DATA`（测试与安装器用）；
2. 打包运行：主程序 EXE 所在目录下的 `data`；
3. 源码运行：仓库根目录下的 `data`。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

DATA_ENV = "NEFGPSTRACK_DATA"
ROUTES_DIR_NAME = "路径库"
APPDATA_DIR_NAME = "程序数据"
LOG_DIR_NAME = "日志"
EXPORT_DIR_NAME = "导出"
SETTINGS_NAME = "settings.json"
INSTALL_INFO_NAME = "安装信息.json"
LEGACY_SETTINGS_NAME = "prefs.json"

_override: Path | None = None


def set_override(value: str | os.PathLike | None) -> None:
    """由命令行 `--data-dir` 调用。"""
    global _override
    text = str(value).strip() if value else ""
    _override = Path(text) if text else None


def install_root() -> Path:
    """程序所在目录：打包后是 EXE 所在目录，源码运行时是仓库根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def data_root() -> Path:
    if _override is not None:
        return _override
    env = os.environ.get(DATA_ENV, "").strip()
    if env:
        return Path(env)
    return install_root() / "data"


def routes_dir() -> Path:
    return data_root() / ROUTES_DIR_NAME


def export_dir() -> Path:
    return routes_dir() / EXPORT_DIR_NAME


def appdata_dir() -> Path:
    return data_root() / APPDATA_DIR_NAME


def logs_dir() -> Path:
    return appdata_dir() / LOG_DIR_NAME


def settings_file() -> Path:
    return appdata_dir() / SETTINGS_NAME


def legacy_settings_file() -> Path:
    """旧位置（1.4.x 的 prefs.json）与旧名，用于兜底读取。"""
    return appdata_dir() / LEGACY_SETTINGS_NAME


def ensure() -> Path:
    """建立数据目录骨架。已存在的一律不动，不删除任何内容。"""
    for path in (routes_dir(), export_dir(), appdata_dir(), logs_dir()):
        path.mkdir(parents=True, exist_ok=True)
    return data_root()
