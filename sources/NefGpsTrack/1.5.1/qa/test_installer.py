"""安装器核心逻辑回归：检测、可写性、安装、升级、迁移、卸载项。

全部用临时目录与**临时注册表根**，不碰真实的卸载项、开始菜单或任何系统位置。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "installer"))

import core  # noqa: E402

TEST_REG = r"Software\TujiInstallerTest"


class InstallerCore(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tuji-installer-"))
        self.payload = self.tmp / "payload.exe"
        self.payload.write_bytes(b"MZ" + b"\x00" * 4096)
        self.target = self.tmp / "install"
        core.remove_uninstall_entries(TEST_REG)

    def tearDown(self):
        core.remove_uninstall_entries(TEST_REG)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------ 检测
    def test_detect_returns_none_before_install(self):
        self.assertIsNone(core.detect_install(reg_root=TEST_REG))

    def test_detect_finds_install_and_version(self):
        core.install(self.payload, self.target, "1.5.1", reg_root=TEST_REG,
                     shortcut=self.tmp / "skip.lnk")
        found = core.detect_install(reg_root=TEST_REG)
        self.assertIsNotNone(found)
        self.assertEqual(found["location"], self.target)
        self.assertEqual(found["version"], "1.5.1")

    def test_detect_ignores_entry_whose_folder_is_gone(self):
        core.install(self.payload, self.target, "1.5.1", reg_root=TEST_REG,
                     shortcut=self.tmp / "skip.lnk")
        import shutil
        shutil.rmtree(self.target)
        # 卸载项还在但目录没了：当作未安装，避免升级到一个不存在的路径。
        self.assertIsNone(core.detect_install(reg_root=TEST_REG))

    # ------------------------------------------------------------ 可写性
    def test_writable_check_rejects_path_under_a_file(self):
        blocker = self.tmp / "blocker"
        blocker.write_bytes(b"x")
        ok, reason = core.check_writable(blocker / "sub")
        self.assertFalse(ok)
        self.assertTrue(reason)

    def test_writable_check_accepts_normal_and_nested(self):
        self.assertTrue(core.check_writable(self.tmp / "fine")[0])
        self.assertTrue(core.check_writable(self.tmp / "a" / "b" / "c")[0])

    def test_writable_check_leaves_no_probe_file(self):
        target = self.tmp / "probe-target"
        core.check_writable(target)
        self.assertEqual([p.name for p in target.iterdir()], [])

    # ------------------------------------------------------------ 安装
    def test_install_creates_layout_and_program(self):
        result = core.install(self.payload, self.target, "1.5.1", reg_root=TEST_REG,
                              shortcut=self.tmp / "skip.lnk")
        self.assertTrue((self.target / core.EXE_NAME).is_file())
        self.assertTrue((self.target / "data" / "路径库").is_dir())
        self.assertTrue((self.target / "data" / "程序数据").is_dir())
        self.assertTrue((self.target / "data" / "路径库" / "导出").is_dir())
        self.assertTrue((self.target / "data" / "程序数据" / core.INSTALL_INFO_NAME).is_file())
        self.assertEqual(result["version"], "1.5.1")

    def test_upgrade_keeps_existing_data_untouched(self):
        core.install(self.payload, self.target, "1.5.1", reg_root=TEST_REG,
                     shortcut=self.tmp / "skip.lnk")
        route = self.target / "data" / "路径库" / "2026-09-24_1355_连续_115点.clp"
        route.write_bytes(b"KEEP-ME")
        settings = self.target / "data" / "程序数据" / "settings.json"
        settings.write_text(json.dumps({"writeInPlace": True}), encoding="utf-8")

        core.install(self.payload, self.target, "1.5.1", reg_root=TEST_REG,
                     shortcut=self.tmp / "skip.lnk")
        self.assertEqual(route.read_bytes(), b"KEEP-ME")
        self.assertEqual(json.loads(settings.read_text(encoding="utf-8")), {"writeInPlace": True})
        self.assertEqual(core.detect_install(reg_root=TEST_REG)["version"], "1.5.1")

    def test_install_reports_progress_in_order(self):
        seen: list[tuple[str, int]] = []
        core.install(self.payload, self.target, "1.5.1", reg_root=TEST_REG,
                     shortcut=self.tmp / "skip.lnk",
                     progress=lambda message, percent: seen.append((message, percent)))
        self.assertTrue(seen)
        percents = [p for _, p in seen]
        self.assertEqual(percents, sorted(percents))
        self.assertEqual(percents[0], 5)
        self.assertEqual(percents[-1], 100)

    def test_install_rejects_missing_payload(self):
        with self.assertRaises(core.InstallError):
            core.install(self.tmp / "nope.exe", self.target, "1.5.1", reg_root=TEST_REG)

    def test_install_rejects_unwritable_target(self):
        blocker = self.tmp / "blocker"
        blocker.write_bytes(b"x")
        with self.assertRaises(core.InstallError):
            core.install(self.payload, blocker / "sub", "1.5.1", reg_root=TEST_REG)

    # ------------------------------------------------------------ 旧数据迁移
    def _make_legacy(self) -> Path:
        legacy = self.tmp / "legacyRoot"
        (legacy / "routes").mkdir(parents=True)
        (legacy / "routes" / ("a" * 32 + ".clp")).write_bytes(b"OLD1")
        (legacy / "routes" / ("b" * 32 + ".clp")).write_bytes(b"OLD2")
        (legacy / "prefs.json").write_text(json.dumps({"writeInPlace": True, "trackMode": "merge"}),
                                           encoding="utf-8")
        return legacy

    def test_migrate_copies_routes_and_settings_without_deleting_source(self):
        legacy = self._make_legacy()
        core.install(self.payload, self.target, "1.5.1", reg_root=TEST_REG,
                     shortcut=self.tmp / "skip.lnk")
        result = core.migrate_legacy(legacy, self.target)
        self.assertTrue(result["found"])
        self.assertEqual(result["routes"], 2)
        self.assertTrue(result["settings"])
        routes = sorted(p.name for p in (self.target / "data" / "路径库").glob("*.clp"))
        self.assertEqual(routes, ["a" * 32 + ".clp", "b" * 32 + ".clp"])
        # 原目录整份保留，一个文件都不能少。
        self.assertEqual(len(list((legacy / "routes").glob("*.clp"))), 2)
        self.assertTrue((legacy / "prefs.json").is_file())
        settings = json.loads((self.target / "data" / "程序数据" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(settings["trackMode"], "merge")

    def test_migrate_is_idempotent_and_never_overwrites(self):
        legacy = self._make_legacy()
        core.install(self.payload, self.target, "1.5.1", reg_root=TEST_REG,
                     shortcut=self.tmp / "skip.lnk")
        first = core.migrate_legacy(legacy, self.target)
        second = core.migrate_legacy(legacy, self.target)
        self.assertEqual(first["routes"], 2)
        self.assertEqual(second["routes"], 0)
        self.assertEqual(second["skipped"], 2)

    def test_migrate_reports_absence(self):
        result = core.migrate_legacy(self.tmp / "nothing", self.target)
        self.assertFalse(result["found"])
        self.assertEqual(result["routes"], 0)

    def test_install_with_migration_in_one_call(self):
        legacy = self._make_legacy()
        result = core.install(self.payload, self.target, "1.5.1", reg_root=TEST_REG,
                              shortcut=self.tmp / "skip.lnk", migrate=True, legacy_root=legacy)
        self.assertEqual(result["migrated"]["routes"], 2)

    # ------------------------------------------------------------ 卸载项
    def test_remove_uninstall_entries(self):
        core.install(self.payload, self.target, "1.5.1", reg_root=TEST_REG,
                     shortcut=self.tmp / "skip.lnk")
        self.assertTrue(core.remove_uninstall_entries(TEST_REG))
        self.assertIsNone(core.detect_install(reg_root=TEST_REG))
        self.assertFalse(core.remove_uninstall_entries(TEST_REG))

    # ------------------------------------------------------------ 环境
    def test_default_install_dir_is_under_local_appdata(self):
        path = core.default_install_dir()
        self.assertEqual(path.name, core.APP_NAME)
        self.assertIn("Programs", path.parts)


if __name__ == "__main__":
    unittest.main()
