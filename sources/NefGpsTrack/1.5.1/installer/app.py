"""途记安装器。

启动后先查本机是否已安装：
- 已安装 → 显示原安装位置与版本，只给「开始升级」，按原路径覆盖并保留 data；
- 未安装 → 让用户选择安装路径（默认免提权位置），可写性检查通过才允许安装。

载荷（主程序 EXE）由 PyInstaller 以 `payload/途记.exe` 打进本安装器。
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import (  # noqa: E402
    APP_NAME, DATA_DIR_NAME, EXE_NAME, InstallError, check_writable,
    default_install_dir, detect_install, install, legacy_data_root,
)

VERSION = "1.5.1"


def payload_path() -> Path:
    """安装载荷位置：打包后在 _MEIPASS/payload，源码运行时在 installer/payload。"""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    bundled = root / "payload" / EXE_NAME
    if bundled.is_file():
        return bundled
    return Path(__file__).resolve().parent / "payload" / EXE_NAME


class Api:
    def __init__(self) -> None:
        self.window = None
        self.lock = threading.RLock()
        self.busy = False
        self.result: dict | None = None

    # ------------------------------------------------------------ 查询
    def probe(self) -> dict:
        installed = None
        try:
            found = detect_install()
        except Exception as exc:  # 注册表不可用也要能继续装
            found = None
            probe_error = str(exc)
        else:
            probe_error = ""
        if found:
            installed = {"location": str(found["location"]), "version": found["version"]}
        legacy = legacy_data_root()
        payload = payload_path()
        return {
            "app": APP_NAME,
            "version": VERSION,
            "installed": installed,
            "defaultDir": str(default_install_dir()),
            "dataFolder": DATA_DIR_NAME,
            "legacy": {"found": legacy.is_dir(), "path": str(legacy)},
            "payloadReady": payload.is_file(),
            "payloadBytes": payload.stat().st_size if payload.is_file() else 0,
            "probeError": probe_error,
        }

    def check(self, args: dict) -> dict:
        path = str((args or {}).get("path") or "").strip()
        if not path:
            return {"writable": False, "reason": "请输入安装位置"}
        ok, reason = check_writable(Path(path))
        return {"writable": ok, "reason": reason, "path": path}

    def pick(self) -> dict:
        import webview
        chosen = self.window.create_file_dialog(webview.FileDialog.FOLDER)
        if not chosen:
            return {"cancelled": True}
        path = chosen if isinstance(chosen, str) else chosen[0]
        return {"path": str(path)}

    # ------------------------------------------------------------ 安装
    def run(self, args: dict) -> dict:
        import webview  # noqa: F401
        args = args or {}
        with self.lock:
            if self.busy:
                raise ValueError("安装正在进行中")
        payload = payload_path()
        if not payload.is_file():
            raise ValueError("安装载荷缺失，请重新下载安装程序")
        mode = str(args.get("mode") or "install")
        target = Path(str(args.get("target") or "").strip() or default_install_dir())
        migrate = bool(args.get("migrate", True))
        try:
            found = detect_install()
        except Exception:
            found = None
        # 升级模式使用检测到的原路径，忽略界面传来的路径，避免误装到别处。
        if mode == "upgrade" and found:
            target = found["location"]
        with self.lock:
            self.busy = True
        threading.Thread(target=self._install, args=(payload, target, mode, migrate), daemon=True).start()
        return {"started": True, "target": str(target)}

    def _install(self, payload: Path, target: Path, mode: str, migrate: bool) -> None:
        def progress(message: str, percent: int) -> None:
            if self.window is None:
                return
            try:
                self.window.evaluate_js(
                    f"window.installProgress({json.dumps(message, ensure_ascii=False)},{int(percent)})")
            except Exception:
                pass

        try:
            result = install(payload, target, VERSION, progress=progress,
                             migrate=migrate, source_note=f"installer-{mode}")
            payload_out = {
                "ok": True,
                "target": str(result["target"]),
                "exe": str(result["installed"]),
                "migrated": result["migrated"],
                "shortcut": str(result["shortcut"]) if result["shortcut"] else "",
                "mode": mode,
            }
        except InstallError as exc:
            payload_out = {"ok": False, "error": str(exc), "mode": mode}
        except Exception as exc:  # 兜底：任何异常都要让界面有反馈
            payload_out = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "mode": mode}
        with self.lock:
            self.busy = False
            self.result = payload_out
        if self.window is not None:
            try:
                self.window.evaluate_js("window.installDone(" + json.dumps(payload_out, ensure_ascii=False) + ")")
            except Exception:
                pass

    def finish(self, args: dict) -> dict:
        import webview  # noqa: F401
        action = str((args or {}).get("action") or "close")
        if action == "launch" and self.result and self.result.get("ok"):
            import subprocess
            try:
                subprocess.Popen([self.result["exe"]], cwd=str(Path(self.result["exe"]).parent))
            except OSError:
                pass
        if self.window is not None:
            self.window.destroy()
        return {"closed": True}


class Bridge:
    """只暴露显式分发器。"""

    def __init__(self, api: Api) -> None:
        self._api = api

    def request(self, action: str, args: dict | None = None):
        api = self._api
        table = {
            "probe": lambda: api.probe(),
            "check": lambda: api.check(args or {}),
            "pick": lambda: api.pick(),
            "run": lambda: api.run(args or {}),
            "finish": lambda: api.finish(args or {}),
        }
        handler = table.get(action)
        if handler is None:
            return {"error": f"未知操作：{action}"}
        try:
            return handler()
        except Exception as exc:
            return {"error": str(exc)}


def cli(argv: list[str]) -> int | None:
    """无人值守入口：供自动化与静默安装使用。没有这些参数时返回 None 走图形界面。

    --probe                                  打印探测结果 JSON
    --silent-install <目录>                   静默安装到指定目录
    --silent-upgrade                          按已安装路径静默升级
    --no-migrate                              静默模式下不迁移旧数据
    --reg-root <注册表子键>                    测试用：改写到临时卸载项根
    --shortcut <lnk 路径>                     测试用：改写到临时快捷方式位置
    """
    if not argv:
        return None
    options = {"migrate": True, "reg_root": None, "shortcut": None, "target": None}
    action = argv[0]
    if action not in ("--probe", "--silent-install", "--silent-upgrade"):
        return None
    rest = argv[1:]
    index = 0
    while index < len(rest):
        item = rest[index]
        if item == "--no-migrate":
            options["migrate"] = False
        elif item == "--reg-root" and index + 1 < len(rest):
            index += 1
            options["reg_root"] = rest[index]
        elif item == "--shortcut" and index + 1 < len(rest):
            index += 1
            options["shortcut"] = Path(rest[index])
        elif item.startswith("--"):
            raise SystemExit(f"未知参数：{item}")
        elif options["target"] is None:
            options["target"] = Path(item)
        index += 1

    if action == "--probe":
        print(json.dumps(Api().probe(), ensure_ascii=False))
        return 0

    target = options["target"]
    if action == "--silent-upgrade":
        found = detect_install(reg_root=options["reg_root"])
        if not found:
            print(json.dumps({"ok": False, "error": "本机未安装途记，无法升级"}, ensure_ascii=False))
            return 2
        target = found["location"]
    if target is None:
        target = default_install_dir()

    try:
        result = install(payload_path(), target, VERSION, reg_root=options["reg_root"],
                         migrate=options["migrate"], shortcut=options["shortcut"],
                         source_note="silent")
    except InstallError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 3
    print(json.dumps({
        "ok": True, "target": str(result["target"]), "exe": str(result["installed"]),
        "version": result["version"], "migrated": result["migrated"],
        "shortcut": str(result["shortcut"]) if result["shortcut"] else "",
        "action": "upgrade" if action == "--silent-upgrade" else "install",
    }, ensure_ascii=False))
    return 0


def main() -> None:
    import sys as _sys
    code = cli(_sys.argv[1:])
    if code is not None:
        raise SystemExit(code)
    import webview
    api = Api()
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    ui = root / "ui" / "index.html"
    if not ui.is_file():
        ui = Path(__file__).resolve().parent / "ui" / "index.html"
    window = webview.create_window(f"{APP_NAME} {VERSION} 安装程序", str(ui), js_api=Bridge(api),
                                   width=680, height=620, min_size=(600, 540),
                                   background_color="#f3f8ff", resizable=True)
    api.window = window
    webview.start(gui="edgechromium", private_mode=True)


if __name__ == "__main__":
    main()
