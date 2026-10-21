"""Read and write EXIF GPS fields through official ExifTool.

1.5.1 起支持 NEF、DNG、JPG/JPEG、PNG、HEIC/HEIF。这几种格式的 GPS 标签在 ExifTool 眼里
都归 `GPS:` 组（PNG 的 EXIF 存在 eXIf 块、HEIF 存在 BMFF 的 EXIF item 里，ExifTool 都会
映射成同一组名），所以写、读回、清理三处的参数完全一致，不需要按格式分支。
实测记录见 analysis/iterations/2026-10-06-multi-format/README.md。
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clp_codec import TrackPoint


class ExifToolError(RuntimeError):
    pass


# 支持写入 GPS 的照片格式；ExifTool 报出的 FileType 与扩展名的对应见 FILE_TYPES。
SUPPORTED_SUFFIXES = (".nef", ".dng", ".jpg", ".jpeg", ".png", ".heic", ".heif")
FILE_TYPES = {
    ".nef": ("NEF",),
    ".dng": ("DNG",),
    ".jpg": ("JPEG",),
    ".jpeg": ("JPEG",),
    ".png": ("PNG",),
    ".heic": ("HEIC", "HEIF"),
    ".heif": ("HEIC", "HEIF"),
}
SUFFIX_LABEL = "、".join(s.lstrip(".").upper() for s in SUPPORTED_SUFFIXES)


def is_supported_photo(path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_SUFFIXES


def _require_supported(photo: Path) -> None:
    if not is_supported_photo(photo):
        raise ExifToolError("仅允许处理受支持格式的照片副本：" + SUFFIX_LABEL)


def file_type_ok(path, file_type) -> bool:
    """扩展名与 ExifTool 报出的 FileType 是否自洽。空 FileType 视为不可读。"""
    expected = FILE_TYPES.get(Path(path).suffix.lower())
    if not expected or not file_type:
        return False
    return str(file_type).upper() in expected


def bundled_exiftool() -> Path:
    override = os.environ.get("NEFGPSTRACK_EXIFTOOL")
    if override:
        return Path(override)
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "exiftool" / "exiftool.exe"


class ExifTool:
    def __init__(self, executable: Path | None = None) -> None:
        self.executable = executable or bundled_exiftool()
        if not self.executable.is_file():
            raise ExifToolError(f"找不到 ExifTool：{self.executable}")

    def _run(self, args: list[str], timeout: int = 120) -> str:
        env = os.environ.copy()
        # Bundled Strawberry Perl otherwise warns about the host's C.UTF-8 locale.
        env["LANG"] = "C"
        env["LC_ALL"] = "C"
        try:
            completed = subprocess.run(
                [str(self.executable), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExifToolError(f"ExifTool 无法运行：{exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise ExifToolError(f"ExifTool 返回 {completed.returncode}：{detail}")
        return completed.stdout

    def version(self) -> str:
        return self._run(["-ver"], timeout=20).strip()

    def metadata(self, photo: Path, *, numeric: bool = False) -> dict[str, Any]:
        args = ["-j", "-G1", "-s"]
        if numeric:
            args.append("-n")
        args += [
            "-FileType", "-DateTimeOriginal", "-SubSecTimeOriginal",
            "-OffsetTimeOriginal", "-GPS:all", str(photo),
        ]
        data = self._run(args, timeout=60)
        try:
            records = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ExifToolError("ExifTool 返回的 JSON 无法解析。") from exc
        if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
            raise ExifToolError("ExifTool 未返回恰好一张照片的数据。")
        record = records[0]
        if "Error" in record or "File:Error" in record:
            raise ExifToolError(str(record.get("Error", record.get("File:Error"))))
        return record

    @staticmethod
    def has_existing_gps(metadata: dict[str, Any]) -> bool:
        # A partial GPS IFD is still user data. Never silently merge into it.
        return any(key.startswith("GPS:") for key in metadata)

    @staticmethod
    def has_existing_position(metadata: dict[str, Any]) -> bool:
        """只有真正的定位数据才算「已有位置」。

        相机常写入只含 GPSVersionID / GPSDateStamp 的空 GPS IFD，那不是定位数据，
        不该拦住补录。判定只看经纬度与海拔三者中有没有实际取值。
        """
        for tag in ("GPS:GPSLatitude", "GPS:GPSLongitude", "GPS:GPSAltitude"):
            value = metadata.get(tag)
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return True
        return False

    def clear_gps(self, photo_copy: Path) -> None:
        _require_supported(photo_copy)
        self._run(["-overwrite_original", "-P", "-GPS:all=", str(photo_copy)], timeout=180)
        if self.has_existing_gps(self.metadata(photo_copy)):
            raise ExifToolError("旧 GPS IFD 清理后仍有 GPS 标签。")

    def write_gps(self, photo_copy: Path, point: TrackPoint) -> None:
        _require_supported(photo_copy)
        fix = datetime.fromtimestamp(point.t / 1000, timezone.utc)
        millis = point.t % 1000
        args = [
            "-overwrite_original", "-P",
            "-GPS:GPSVersionID=2 3 0 0",
            f"-GPS:GPSLatitudeRef={'N' if point.lat >= 0 else 'S'}",
            f"-GPS:GPSLatitude={abs(point.lat):.9f}",
            f"-GPS:GPSLongitudeRef={'E' if point.lon >= 0 else 'W'}",
            f"-GPS:GPSLongitude={abs(point.lon):.9f}",
            f"-GPS:GPSDateStamp={fix:%Y:%m:%d}",
            f"-GPS:GPSTimeStamp={fix:%H:%M:%S}.{millis:03d}",
            "-GPS:GPSMapDatum=WGS-84",
        ]
        if point.alt is not None:
            args += [
                f"-GPS:GPSAltitudeRef#={0 if point.alt >= 0 else 1}",
                f"-GPS:GPSAltitude={abs(point.alt):.3f}",
            ]
        args.append(str(photo_copy))
        self._run(args, timeout=180)

    def verify_gps(self, photo_copy: Path, point: TrackPoint) -> None:
        metadata = self.metadata(photo_copy, numeric=True)
        def value(name: str) -> Any:
            if f"GPS:{name}" not in metadata:
                raise ExifToolError(f"读回缺少 GPS:{name}。")
            return metadata[f"GPS:{name}"]

        if str(value("GPSVersionID")) != "2 3 0 0":
            raise ExifToolError("读回 GPSVersionID 不一致。")
        if str(value("GPSLatitudeRef")) != ("N" if point.lat >= 0 else "S"):
            raise ExifToolError("读回纬度方向不一致。")
        if str(value("GPSLongitudeRef")) != ("E" if point.lon >= 0 else "W"):
            raise ExifToolError("读回经度方向不一致。")
        for tag, expected in (("GPSLatitude", abs(point.lat)), ("GPSLongitude", abs(point.lon))):
            try:
                actual = float(value(tag))
            except (TypeError, ValueError) as exc:
                raise ExifToolError(f"读回 {tag} 不是数值。") from exc
            if not math.isclose(actual, expected, rel_tol=0, abs_tol=1e-6):
                raise ExifToolError(f"读回 {tag} 与轨迹点不一致。")
        fix = datetime.fromtimestamp(point.t / 1000, timezone.utc)
        if str(value("GPSDateStamp")) != fix.strftime("%Y:%m:%d"):
            raise ExifToolError("读回 GPSDateStamp 不一致。")
        time_text = str(value("GPSTimeStamp"))
        try:
            hh, mm, seconds = time_text.split(":")
            actual_seconds = int(hh) * 3600 + int(mm) * 60 + float(seconds)
        except (ValueError, TypeError) as exc:
            raise ExifToolError("读回 GPSTimeStamp 格式无效。") from exc
        expected_seconds = fix.hour * 3600 + fix.minute * 60 + fix.second + point.t % 1000 / 1000
        if abs(actual_seconds - expected_seconds) > 0.05:
            raise ExifToolError("读回 GPSTimeStamp 与定位时间不一致。")
        if str(value("GPSMapDatum")) != "WGS-84":
            raise ExifToolError("读回 GPSMapDatum 不一致。")
        if point.alt is None:
            if "GPS:GPSAltitude" in metadata or "GPS:GPSAltitudeRef" in metadata:
                raise ExifToolError("未知海拔时意外写入海拔。")
        else:
            if int(value("GPSAltitudeRef")) != (0 if point.alt >= 0 else 1):
                raise ExifToolError("读回海拔方向不一致。")
            if not math.isclose(float(value("GPSAltitude")), abs(point.alt), rel_tol=0, abs_tol=0.2):
                raise ExifToolError("读回海拔与轨迹点不一致。")
        if "GPS:GPSSatellites" in metadata:
            raise ExifToolError("意外写入了未测得的卫星数。")
