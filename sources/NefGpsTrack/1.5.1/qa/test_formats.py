"""多格式写入回归：DNG / JPG / PNG / HEIC 与 NEF 走同一条写入→读回→清理链路。

夹具在 `qa/formats/`，都是**合成**文件（用 tifffile 造 TIFF 后打 DNG 标记、Pillow 生成
JPG/PNG、pillow-heif 生成 HEIC），不含任何真实拍摄内容，可以随源码归档。
每次测试只操作临时目录里的副本，夹具本身只读。

需要 ExifTool：用环境变量 `NEFGPSTRACK_EXIFTOOL` 指定，缺省走打包时的常见位置。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows"))

from clp_codec import TrackPoint  # noqa: E402
from exiftool_io import (  # noqa: E402
    FILE_TYPES, SUPPORTED_SUFFIXES, ExifTool, ExifToolError, file_type_ok,
    is_supported_photo,
)

FORMATS_DIR = Path(__file__).resolve().parent / "formats"
# 合成夹具里没有真实拍摄时间，用一个固定的假时刻即可：链路只关心写入与读回是否一致。
POINT = TrackPoint(1790221525012, 1.1100000, 2.1000000, 1513.5, 8.0, None, None, "curve")


def exiftool_path() -> Path | None:
    override = os.environ.get("NEFGPSTRACK_EXIFTOOL")
    if override and Path(override).is_file():
        return Path(override)
    for candidate in (
        Path(r"D:\Codex\途记专项\temp\NefGpsTrack-1.5.0-windows\vendor\exiftool-13.59_64\exiftool.exe"),
    ):
        if candidate.is_file():
            return candidate
    return None


class Formats(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = exiftool_path()
        if path is None:
            raise unittest.SkipTest("找不到 ExifTool，设置 NEFGPSTRACK_EXIFTOOL 后重跑")
        cls.exif = ExifTool(path)
        cls.fixtures = sorted(p for p in FORMATS_DIR.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES)
        if not cls.fixtures:
            raise unittest.SkipTest("qa/formats 下没有夹具")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tuji-fmt-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------ 常量
    def test_supported_suffixes_are_the_documented_set(self):
        self.assertEqual(SUPPORTED_SUFFIXES,
                         (".nef", ".dng", ".jpg", ".jpeg", ".png", ".heic", ".heif"))
        for name in ("a.nef", "a.dng", "a.jpg", "a.jpeg", "a.png", "a.heic", "a.heif"):
            self.assertTrue(is_supported_photo(name), name)
        for name in ("a.tif", "a.bmp", "a.txt", "a"):
            self.assertFalse(is_supported_photo(name), name)

    def test_file_type_mapping_is_self_consistent(self):
        self.assertTrue(file_type_ok("a.jpg", "JPEG"))
        self.assertTrue(file_type_ok("a.JPEG", "JPEG"))
        self.assertTrue(file_type_ok("a.heic", "HEIC"))
        self.assertTrue(file_type_ok("a.heif", "HEIF"))
        self.assertTrue(file_type_ok("a.dng", "DNG"))
        # 扩展名与内容不符、或读不到类型时都必须判为不通过
        self.assertFalse(file_type_ok("a.png", "JPEG"))
        self.assertFalse(file_type_ok("a.nef", None))
        self.assertFalse(file_type_ok("a.tif", "TIFF"))

    def test_every_fixture_is_identified_as_expected(self):
        for fixture in self.fixtures:
            with self.subTest(fixture.name):
                meta = self.exif.metadata(fixture)
                self.assertTrue(file_type_ok(fixture, meta.get("File:FileType")),
                                f"{fixture.name} 的 FileType 是 {meta.get('File:FileType')}")
                self.assertIn(meta.get("File:FileType"), FILE_TYPES[fixture.suffix.lower()])

    # ------------------------------------------------------------ 主链路
    def test_write_verify_clear_round_trip_for_every_format(self):
        for fixture in self.fixtures:
            with self.subTest(fixture.name):
                target = self.tmp / fixture.name
                shutil.copy2(fixture, target)
                before = self.exif.metadata(target)
                self.assertFalse(self.exif.has_existing_position(before),
                                 f"{fixture.name} 的夹具本来就带了定位")
                self.exif.write_gps(target, POINT)
                # verify_gps 内部会抛错，能跑到下一行就说明坐标、时间、海拔都读回一致
                self.exif.verify_gps(target, POINT)
                self.assertTrue(self.exif.has_existing_position(self.exif.metadata(target)))
                self.exif.clear_gps(target)
                self.assertFalse(self.exif.has_existing_position(self.exif.metadata(target)))
                numeric = self.exif.metadata(target, numeric=True)
                self.assertNotIn("GPS:GPSAltitude", numeric, "清理后仍有海拔残留")

    def test_overwrite_replaces_an_existing_position(self):
        """有定位时勾选覆盖：旧值被换成新值，且不会两套并存。"""
        for fixture in self.fixtures:
            with self.subTest(fixture.name):
                target = self.tmp / fixture.name
                shutil.copy2(fixture, target)
                first = TrackPoint(POINT.t, 30.0, 100.0, 1000.0, 8.0, None, None, "curve")
                self.exif.write_gps(target, first)
                self.exif.verify_gps(target, first)
                self.exif.clear_gps(target)
                self.exif.write_gps(target, POINT)
                self.exif.verify_gps(target, POINT)
                numeric = self.exif.metadata(target, numeric=True)
                self.assertAlmostEqual(float(numeric["GPS:GPSLatitude"]), abs(POINT.lat), places=6)

    def test_unknown_altitude_writes_no_altitude(self):
        """海拔未知时不许写入海拔，四种格式都必须守住。"""
        blank = TrackPoint(POINT.t, POINT.lat, POINT.lon, None, 8.0, None, None, "curve")
        for fixture in self.fixtures:
            with self.subTest(fixture.name):
                target = self.tmp / fixture.name
                shutil.copy2(fixture, target)
                self.exif.write_gps(target, blank)
                self.exif.verify_gps(target, blank)
                numeric = self.exif.metadata(target, numeric=True)
                self.assertNotIn("GPS:GPSAltitude", numeric)
                self.assertNotIn("GPS:GPSAltitudeRef", numeric)

    def test_unsupported_suffix_is_refused(self):
        for name in ("note.txt", "shot.tif", "shot.bmp"):
            target = self.tmp / name
            target.write_bytes(b"x")
            with self.assertRaises(ExifToolError, msg=name):
                self.exif.write_gps(target, POINT)

    def test_fixtures_are_never_modified(self):
        """夹具是只读证据，任何一轮测试都不许改动它。"""
        for fixture in self.fixtures:
            with self.subTest(fixture.name):
                self.assertFalse(self.exif.has_existing_position(self.exif.metadata(fixture)),
                                 f"{fixture.name} 被写脏了")


if __name__ == "__main__":
    unittest.main(verbosity=2)
