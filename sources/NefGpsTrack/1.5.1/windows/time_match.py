"""Convert camera exposure time to UTC and select a quality-controlled GPS fix."""

from __future__ import annotations

import bisect
import math
import re
from dataclasses import dataclass, asdict, replace
from curve import build_curve, evaluate
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from clp_codec import TrackPoint


MAX_INTERPOLATION_GAP_MS = 120_000
MAX_NEAREST_AGE_MS = 60_000
MAX_HACC_METERS = 100.0
EXIF_TIME_RE = re.compile(r"^(\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2})(?:\.(\d+))?$")
OFFSET_RE = re.compile(r"^([+-])(\d{2}):(\d{2})$")


class MatchError(ValueError):
    pass


@dataclass(frozen=True)
class Match:
    point: TrackPoint
    method: str
    age_ms: int
    source_before_ms: int
    source_after_ms: int | None


@dataclass(frozen=True)
class TrackIndex:
    points: tuple[TrackPoint, ...]
    times: tuple[int, ...]
    curve: dict
    mode: str = "track"


def build_track_index(
    points: Sequence[TrackPoint], *, max_hacc: float = MAX_HACC_METERS, mode: str = "track"
) -> TrackIndex:
    unique = {}
    for p in points:
        if p.hacc is not None and p.hacc <= max_hacc and (p.t not in unique or p.hacc < unique[p.t].hacc):
            unique[p.t] = p
    accurate = tuple(unique[t] for t in sorted(unique))
    return TrackIndex(accurate, tuple(p.t for p in accurate), build_curve([asdict(p) for p in accurate]), mode)


def metadata_tag(metadata: dict[str, Any], name: str) -> Any:
    for group in ("ExifIFD", "IFD0", "EXIF"):
        key = f"{group}:{name}"
        if key in metadata:
            return metadata[key]
    for key, value in metadata.items():
        if key.endswith(f":{name}"):
            return value
    return None


def parse_offset(value: str) -> timezone:
    if value == "Z":
        return timezone.utc
    match = OFFSET_RE.fullmatch(value)
    if not match:
        raise MatchError("时区须写成 +08:00 或 -05:30。")
    sign, hh, mm = match.groups()
    hours, minutes = int(hh), int(mm)
    if hours > 14 or minutes > 59 or (hours == 14 and minutes != 0):
        raise MatchError("时区偏移超出有效范围。")
    delta = timedelta(hours=hours, minutes=minutes)
    return timezone(delta if sign == "+" else -delta)


def capture_utc_ms(
    metadata: dict[str, Any], default_offset: str, correction_seconds: float
) -> tuple[int, str]:
    value = metadata_tag(metadata, "DateTimeOriginal")
    if not isinstance(value, str):
        raise MatchError("缺少 DateTimeOriginal。")
    match = EXIF_TIME_RE.fullmatch(value.strip())
    if not match:
        raise MatchError("DateTimeOriginal 格式无法识别。")
    try:
        local = datetime.strptime(match.group(1), "%Y:%m:%d %H:%M:%S")
    except ValueError as exc:
        raise MatchError("DateTimeOriginal 日期无效。") from exc
    subsec = metadata_tag(metadata, "SubSecTimeOriginal")
    digits = str(subsec).strip() if subsec is not None else (match.group(2) or "")
    digits = digits.lstrip(".")
    if digits:
        if not digits.isdigit():
            raise MatchError("SubSecTimeOriginal 不是数字。")
        local = local.replace(microsecond=int((digits + "000000")[:6]))
    original_offset = metadata_tag(metadata, "OffsetTimeOriginal")
    offset_text = str(original_offset).strip() if original_offset else default_offset.strip()
    zone = parse_offset(offset_text)
    if not isinstance(correction_seconds, (int, float)) or not math.isfinite(correction_seconds):
        raise MatchError("相机时钟校正秒数无效。")
    utc = local.replace(tzinfo=zone).astimezone(timezone.utc)
    delta = utc - datetime(1970, 1, 1, tzinfo=timezone.utc)
    millis = round(delta.total_seconds() * 1000 + correction_seconds * 1000)
    return millis, offset_text


def match_track(
    points: Sequence[TrackPoint] | TrackIndex, capture_ms: int,
    *, max_hacc: float = MAX_HACC_METERS,
    max_interpolation_gap_ms: int = MAX_INTERPOLATION_GAP_MS,
    max_nearest_age_ms: int = MAX_NEAREST_AGE_MS,
) -> Match | None:
    index = points if isinstance(points, TrackIndex) else build_track_index(points, max_hacc=max_hacc)
    eligible = index.points
    if not eligible:
        return None
    if index.mode == "single":
        if len(eligible) != 1:
            raise MatchError("单点补录须恰好包含一个定位点。")
        p = eligible[0]
        return Match(replace(p, t=capture_ms), "single", abs(p.t-capture_ms), p.t, None)
    value = evaluate(index.curve, capture_ms)
    if value is None:
        return None
    i = bisect.bisect_left(index.times, capture_ms)
    if i < len(eligible) and eligible[i].t == capture_ms:
        p = eligible[i]
        return Match(p, "exact", 0, p.t, None)
    before, after = eligible[i-1], eligible[i]
    p = TrackPoint(capture_ms, value[0], value[1], value[2], max(before.hacc,after.hacc), None, None, "curve")
    method = "curve-long-gap" if after.t-before.t > MAX_INTERPOLATION_GAP_MS else "interpolated"
    return Match(p, method, 0, before.t, after.t)



def utc_text(millis: int | None) -> str:
    if millis is None:
        return ""
    try:
        dt = datetime.fromtimestamp(millis / 1000, timezone.utc)
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return str(millis)
