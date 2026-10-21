"""安装器核心逻辑：检测、可写性、安装、升级、旧数据迁移、卸载项。

这里不放任何界面代码，全部函数都能在无人值守下测试：
- 注册表操作都接受 `reg_root`，测试时指向临时根，不污染真实卸载项；
- 文件操作只碰调用方给出的路径，不读环境里的隐式位置（除 `default_install_dir` 与
  `legacy_data_root` 这两个明确取环境变量的函数）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Callable

APP_NAME = "途记"
APP_ID = "NefGpsTrack"
EXE_NAME = "途记.exe"
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"
PUBLISHER = "途记"
DATA_DIR_NAME = "data"
ROUTES_DIR_NAME = "路径库"
APPDATA_DIR_NAME = "程序数据"
LOG_DIR_NAME = "日志"
EXPORT_DIR_NAME = "导出"
LEGACY_ROUTE_NAME = "routes"
LEGACY_SETTINGS_NAME = "prefs.json"
SETTINGS_NAME = "settings.json"
INSTALL_INFO_NAME = "安装信息.json"

Progress = Callable[[str, int], None]


class InstallError(RuntimeError):
    """安装流程中可以直接展示给用户的错误。"""


# ---------------------------------------------------------------- 环境

def default_install_dir() -> Path:
    """默认安装位置：免提权的用户程序目录。"""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Programs" / APP_NAME


def legacy_data_root() -> Path:
    """1.4.x 及更早版本的数据根目录。"""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_ID


def start_menu_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def shortcut_path() -> Path:
    return start_menu_dir() / f"{APP_NAME}.lnk"


# ---------------------------------------------------------------- 注册表

def _winreg():
    import winreg  # 只在 Windows 上存在
    return winreg


def detect_install(reg_root: str | None = None) -> dict | None:
    """读卸载项判断是否已安装。返回 {'location':Path,'version':str} 或 None。"""
    winreg = _winreg()
    root = reg_root if reg_root is not None else rf"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    subkey = APP_ID if reg_root is not None else APP_ID
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{root}\{subkey}") as key:
            location = winreg.QueryValueEx(key, "InstallLocation")[0]
            version = winreg.QueryValueEx(key, "DisplayVersion")[0]
    except (FileNotFoundError, OSError):
        return None
    if not location:
        return None
    path = Path(location)
    if not path.is_dir():
        # 卸载项还在但目录没了：当作未安装，避免升级到一个不存在的路径。
        return None
    return {"location": path, "version": str(version)}


def write_uninstall_entries(target: Path, version: str, exe: Path, *, reg_root: str | None = None,
                            estimated_kb: int | None = None) -> None:
    winreg = _winreg()
    root = reg_root if reg_root is not None else rf"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, rf"{root}\{APP_ID}", 0, winreg.KEY_WRITE) as key:
        values = {
            "DisplayName": APP_NAME,
            "DisplayVersion": version,
            "Publisher": PUBLISHER,
            "DisplayIcon": str(exe),
            "InstallLocation": str(target),
            "UninstallString": f'"{exe}" --uninstall',
            "QuietUninstallString": f'"{exe}" --uninstall --silent',
            "NoModify": 1,
            "NoRepair": 1,
        }
        if estimated_kb:
            values["EstimatedSize"] = int(estimated_kb)
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ if isinstance(value, str) else winreg.REG_DWORD, value)


def remove_uninstall_entries(reg_root: str | None = None) -> bool:
    winreg = _winreg()
    root = reg_root if reg_root is not None else rf"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    try:
        winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, rf"{root}\{APP_ID}")
        return True
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------- 可写性

def check_writable(path: Path) -> tuple[bool, str]:
    """真实写一个临时文件再删掉，别只看权限位。"""
    probe = Path(path)
    try:
        probe.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"无法创建目录：{exc.strerror or exc}"
    target = probe / f".write-probe-{uuid.uuid4().hex}.tmp"
    try:
        target.write_bytes(b"probe")
    except OSError as exc:
        return False, f"该位置不可写（{exc.strerror or exc}），请改选其它位置"
    finally:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
    return True, ""


def running_processes(exe_name: str = EXE_NAME) -> list[int]:
    """按可执行文件名找正在运行的进程，用于升级前确认程序已关闭。"""
    if sys.platform != "win32":
        return []
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    pids: list[int] = []
    for line in completed.stdout.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == exe_name.lower():
            try:
                pids.append(int(parts[1]))
            except ValueError:
                continue
    return pids


# ---------------------------------------------------------------- 数据目录

def data_dir_for(target: Path) -> Path:
    return Path(target) / DATA_DIR_NAME


def routes_dir_for(target: Path) -> Path:
    return data_dir_for(target) / ROUTES_DIR_NAME


def appdata_dir_for(target: Path) -> Path:
    return data_dir_for(target) / APPDATA_DIR_NAME


def ensure_layout(target: Path) -> dict[str, Path]:
    """建立数据目录骨架。已存在的一律不动、不清空。"""
    layout = {
        "data": data_dir_for(target),
        "routes": routes_dir_for(target),
        "export": routes_dir_for(target) / EXPORT_DIR_NAME,
        "appdata": appdata_dir_for(target),
        "logs": appdata_dir_for(target) / LOG_DIR_NAME,
    }
    for path in layout.values():
        path.mkdir(parents=True, exist_ok=True)
    return layout


# ---------------------------------------------------------------- 旧数据迁移

def migrate_legacy(legacy_root: Path, target: Path) -> dict:
    """把旧版数据搬进安装路径。原目录整份保留，不做任何删除。

    这里只做纯文件复制，**不解密 CLP**：安装器不引入 cryptography。
    旧版轨迹的文件名还是 32 位十六进制，主程序首次启动时会按内容改成可读名
    （见 pages 侧 Library.migrate_readable_names）。
    """
    legacy_root = Path(legacy_root)
    result = {"found": legacy_root.is_dir(), "routes": 0, "skipped": 0,
              "settings": False, "kept": str(legacy_root)}
    if not result["found"]:
        return result
    layout = ensure_layout(Path(target))
    routes_src = legacy_root / LEGACY_ROUTE_NAME
    if routes_src.is_dir():
        for source in sorted(routes_src.glob("*.clp")):
            destination = layout["routes"] / source.name
            if destination.exists():
                result["skipped"] += 1
                continue
            shutil.copy2(source, destination)
            result["routes"] += 1
    settings_src = legacy_root / LEGACY_SETTINGS_NAME
    settings_dst = layout["appdata"] / SETTINGS_NAME
    if settings_src.is_file() and not settings_dst.exists():
        try:
            data = json.loads(settings_src.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                settings_dst.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                result["settings"] = True
        except (OSError, ValueError):
            pass
    return result


# ---------------------------------------------------------------- 安装

def install(payload: Path, target: Path, version: str, *, reg_root: str | None = None,
            progress: Progress | None = None, migrate: bool = False,
            legacy_root: Path | None = None, source_note: str = "",
            shortcut: Path | None = None) -> dict:
    """把载荷装到 target。已存在的 data 目录一字不动。"""
    payload = Path(payload)
    target = Path(target)
    if not payload.is_file():
        raise InstallError(f"安装载荷不存在：{payload}")

    def step(message: str, percent: int) -> None:
        if progress:
            progress(message, percent)

    step("检查安装位置", 5)
    writable, reason = check_writable(target)
    if not writable:
        raise InstallError(reason)

    step("准备数据目录", 20)
    layout = ensure_layout(target)

    step("检查程序是否在运行", 30)
    busy = running_processes()
    if busy:
        raise InstallError("途记正在运行，请先关闭后再安装。")

    step("写入程序文件", 50)
    destination = target / EXE_NAME
    staging = target / f"{EXE_NAME}.new"
    try:
        shutil.copy2(payload, staging)
        os.replace(staging, destination)
    except OSError as exc:
        staging.unlink(missing_ok=True)
        raise InstallError(f"写入程序文件失败：{exc}") from exc

    step("记录安装信息", 70)
    info = {
        "name": APP_NAME, "version": version,
        "installedUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "installLocation": str(target), "note": source_note,
    }
    (layout["appdata"] / INSTALL_INFO_NAME).write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    step("登记卸载项", 80)
    try:
        write_uninstall_entries(target, version, destination, reg_root=reg_root,
                                estimated_kb=payload.stat().st_size // 1024)
    except OSError as exc:
        raise InstallError(f"写入注册表失败：{exc}") from exc

    step("创建快捷方式", 88)
    link = create_shortcut(destination, shortcut)

    migrated = {"found": False}
    if migrate:
        step("迁移旧版数据", 94)
        migrated = migrate_legacy(legacy_root or legacy_data_root(), target)

    step("完成", 100)
    return {"installed": destination, "target": target, "layout": layout,
            "shortcut": link, "migrated": migrated, "version": version}


def create_shortcut(exe: Path, path: Path | None = None) -> Path | None:
    """用 PowerShell 的 WScript.Shell 建开始菜单快捷方式；失败不致命。"""
    link = Path(path) if path else shortcut_path()
    link.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{link}');"
        "$s.TargetPath='{exe}';$s.WorkingDirectory='{work}';$s.IconLocation='{exe},0';"
        "$s.Description='{desc}';$s.Save()"
    ).format(link=str(link), exe=str(exe), work=str(exe.parent), desc=APP_NAME)
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return link if completed.returncode == 0 and link.exists() else None


def remove_shortcut(path: Path | None = None) -> bool:
    link = Path(path) if path else shortcut_path()
    try:
        link.unlink()
        return True
    except FileNotFoundError:
        return False
