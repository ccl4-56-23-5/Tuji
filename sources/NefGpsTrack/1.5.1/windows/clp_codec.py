"""CLP1 encrypted track interchange format shared with the Android recorder."""

from __future__ import annotations

import json
import math
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


# Public source does not contain the original distribution password.
# Copy clp_secret.example.py to clp_secret.py locally, or set the environment variable.
try:
    from clp_secret import CLP_PASSWORD as FIXED_KEY
except ImportError:
    FIXED_KEY = os.environ.get("NEFGPSTRACK_CLP_PASSWORD", "")
MAGIC = b"CLP1"
ITERATIONS = 310_000
HEADER_SIZE = 36
MIN_SIZE = HEADER_SIZE + 16
SCHEMA = "nef-gps-track/1"
MAX_FILE_BYTES = 128 * 1024 * 1024
POINT_KEYS = {"t", "lat", "lon", "alt", "hacc", "speed", "bearing", "provider"}


class ClpError(ValueError):
    """The file cannot be authenticated or does not follow CLP1."""


@dataclass(frozen=True)
class TrackPoint:
    t: int
    lat: float
    lon: float
    alt: float | None
    hacc: float | None
    speed: float | None
    bearing: float | None
    provider: str | None


@dataclass(frozen=True)
class Track:
    created_utc_ms: int
    points: tuple[TrackPoint, ...]
    mode: str = "track"


def _key(password: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    if not isinstance(password, str) or not password:
        raise ClpError("请输入 CLP 密码。")
    return PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations
    ).derive(password.encode("utf-8"))


def _pairs_no_duplicates(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ClpError(f"JSON 字段重复：{key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ClpError(f"JSON 包含非法数值：{value}")


def _int64(value: Any, name: str) -> int:
    if type(value) is not int or not -(1 << 63) <= value < (1 << 63):
        raise ClpError(f"{name} 必须是有符号 64 位整数。")
    return value


def _number(value: Any, name: str, *, nullable: bool = False) -> float | None:
    if value is None and nullable:
        return None
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ClpError(f"{name} 必须是有限数值。")
    return float(value)


def _parse_payload(plain: bytes) -> Track:
    try:
        payload = json.loads(
            plain.decode("utf-8", errors="strict"),
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ClpError("CLP 明文不是有效 UTF-8 JSON。") from exc
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ClpError("CLP schema 不受支持。")
    created = _int64(payload.get("createdUtcMs"), "createdUtcMs")
    raw_points = payload.get("points")
    if not isinstance(raw_points, list):
        raise ClpError("points 必须是数组。")
    points: list[TrackPoint] = []
    previous_t: int | None = None
    for index, raw in enumerate(raw_points):
        if not isinstance(raw, dict) or not POINT_KEYS.issubset(raw):
            raise ClpError(f"第 {index + 1} 个轨迹点缺少必填字段。")
        t = _int64(raw["t"], "t")
        if previous_t is not None and t < previous_t:
            raise ClpError("轨迹点必须按 t 升序排列。")
        previous_t = t
        lat = _number(raw["lat"], "lat")
        lon = _number(raw["lon"], "lon")
        alt = _number(raw["alt"], "alt", nullable=True)
        hacc = _number(raw["hacc"], "hacc", nullable=True)
        speed = _number(raw["speed"], "speed", nullable=True)
        bearing = _number(raw["bearing"], "bearing", nullable=True)
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ClpError(f"第 {index + 1} 个轨迹点经纬度越界。")
        if hacc is not None and hacc < 0:
            raise ClpError("hacc 不能为负数。")
        if speed is not None and speed < 0:
            raise ClpError("speed 不能为负数。")
        if bearing is not None and not 0 <= bearing < 360:
            raise ClpError("bearing 必须位于 [0,360)。")
        provider = raw["provider"]
        if provider is not None and not isinstance(provider, str):
            raise ClpError("provider 必须是字符串或 null。")
        points.append(TrackPoint(t, lat, lon, alt, hacc, speed, bearing, provider))
    mode = payload.get("mode", "track")
    if mode not in ("track", "single") or (mode == "single" and len(points) != 1):
        raise ClpError("单点补录须恰好包含一个定位点。")
    return Track(created, tuple(points), mode)


def decrypt_clp(blob: bytes, password: str) -> Track:
    if not isinstance(blob, bytes) or len(blob) < MIN_SIZE:
        raise ClpError("CLP 文件过短。")
    if len(blob) > MAX_FILE_BYTES:
        raise ClpError("CLP 文件超过 128 MiB 上限。")
    if blob[:4] != MAGIC:
        raise ClpError("CLP 文件标识不正确。")
    iterations = struct.unpack_from(">I", blob, 4)[0]
    if iterations != ITERATIONS:
        raise ClpError("CLP 迭代次数不受支持。")
    header = blob[:HEADER_SIZE]
    salt, nonce = header[8:24], header[24:36]
    try:
        plain = AESGCM(_key(password, salt, iterations)).decrypt(
            nonce, blob[HEADER_SIZE:], header
        )
    except InvalidTag as exc:
        raise ClpError("密码错误或 CLP 文件已损坏。") from exc
    return _parse_payload(plain)


def read_clp(path: Path, password: str) -> Track:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ClpError("CLP 文件超过 128 MiB 上限。")
    return decrypt_clp(path.read_bytes(), password)


def encrypt_clp(
    payload: dict[str, Any], password: str, *, salt: bytes | None = None, nonce: bytes | None = None
) -> bytes:
    """Exporter/test helper. Production callers leave salt and nonce random."""
    plain = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    _parse_payload(plain)
    salt = os.urandom(16) if salt is None else salt
    nonce = os.urandom(12) if nonce is None else nonce
    if len(salt) != 16 or len(nonce) != 12:
        raise ClpError("salt 或 nonce 长度错误。")
    header = MAGIC + struct.pack(">I", ITERATIONS) + salt + nonce
    return header + AESGCM(_key(password, salt)).encrypt(nonce, plain, header)
