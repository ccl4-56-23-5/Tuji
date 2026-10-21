"""预览并写入照片 GPS；默认生成副本，也可按设置就地改写原片。

本模块不生成任何表格文件：写入结果只在界面表格与写入预览里呈现。
就地改写时先复制到原片同目录的临时文件，写入并读回验证通过后再原子替换原片；
可在替换前把改写前的原片备份到指定目录。任何一步失败都不会动到原片。

照片来源有两种：拖入/选择的照片文件清单，或一个照片目录。前者以文件清单为准，
按其公共父目录保留相对路径；后者沿用目录扫描。
可选多条轨迹：为每张照片在候选轨迹中按“时间证据强度”选一条，见 pick_track()；
也可把多条轨迹合并成一条曲线，见 merge_sources()。

曲线分工：手机端只做第一步（滤除 GPS 漂移，结果写进 CLP 的 points），
第二步（插值成平滑曲线）由本端在选中 CLP 时完成，见 time_match.build_track_index()。
"""

from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event
from typing import Callable, Sequence

from clp_codec import Track, TrackPoint, read_clp
from exiftool_io import ExifTool, SUPPORTED_SUFFIXES, SUFFIX_LABEL, file_type_ok, is_supported_photo
from time_match import (
    Match, MatchError, TrackIndex, build_track_index, capture_utc_ms, match_track,
)

# 多轨迹择优的优先级：时间证据越强越靠前。
# exact          照片时刻正好等于一个定位点
# interpolated   被前后两个定位点夹住，间隔不超过 120 秒
# curve-long-gap 被夹住但间隔超过 120 秒，属估算
# single         单点补录，位置对任意时刻都成立，但对该照片没有时间证据
MATCH_PRIORITY = {"exact": 0, "interpolated": 1, "curve-long-gap": 2, "single": 3}
METHOD_TEXT = {
    "exact": "精确命中定位点",
    "interpolated": "曲线插值",
    "curve-long-gap": "长间隔估算",
    "single": "单点固定位置",
}


@dataclass(frozen=True)
class Options:
    """一次补录任务的输入。tracks 至少一条；files 非空时以文件清单为准，否则用 photos 目录。"""
    tracks: tuple[Path, ...]
    photos: Path | None
    files: tuple[Path, ...]
    # 副本模式为输出目录（必填）；就地模式为可选的备份目录，留空表示不备份。
    output: Path | None
    default_offset: str
    correction_seconds: float
    overwrite_existing_gps: bool = False
    in_place: bool = False
    # True 时把所选轨迹的节点按时间串成一条曲线；False 时各自成曲线参与择优。
    merge_tracks: bool = False


@dataclass(frozen=True)
class PhotoEntry:
    source: Path
    relative: Path


@dataclass(frozen=True)
class TrackSource:
    path: Path
    label: str
    index: TrackIndex


@dataclass(frozen=True)
class PlanRow:
    source: Path
    relative: Path
    size: int
    mtime_ns: int
    capture_ms: int | None
    offset_used: str
    match: Match | None
    status: str
    reason: str
    # 照片在本次预览里的编号，从 1 起；界面用它把表格行和地图图钉对应起来。
    number: int = 0
    existing_position: bool = False
    has_gps_ifd: bool = False
    track_label: str = ""


@dataclass(frozen=True)
class Plan:
    options: Options
    track_count: int
    rows: tuple[PlanRow, ...]
    photo_root: Path | None = None
    # 本次实际使用的曲线折线：[{"label": str, "points": [[lat, lon], ...]}]，点序即时间序。
    track_lines: tuple[dict, ...] = ()


@dataclass(frozen=True)
class AuditRow:
    plan: PlanRow
    result: str
    detail: str
    destination: Path | None
    # 实际写入照片的坐标；仅 written 行有值，供界面写入预览使用。
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None


def _as_path(value) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    return Path(text) if text else None


def common_root(paths: Sequence[Path]) -> Path | None:
    """文件清单的公共父目录；跨盘符时返回 None（此时相对路径退化为文件名）。"""
    parents = [str(Path(p).parent) for p in paths]
    if not parents:
        return None
    try:
        return Path(os.path.commonpath(parents))
    except ValueError:
        return None


def photo_base(options: Options) -> Path | None:
    if options.files:
        return common_root(options.files)
    return options.photos


def validate_paths(options: Options) -> None:
    if not options.tracks:
        raise ValueError("请至少勾选一条轨迹。")
    for path in options.tracks:
        track = Path(path)
        if not track.is_file() or track.suffix.lower() != ".clp":
            raise ValueError(f"轨迹文件无效：{track.name}")
    if not options.files and (options.photos is None or not Path(options.photos).is_dir()):
        raise ValueError("请先导入照片：把照片拖进窗口，或选择照片目录。")
    base = photo_base(options)
    if options.in_place:
        if options.output is None:
            return
        backup = options.output.resolve(strict=False)
        if base is not None and (backup == base or base in backup.parents or backup in base.parents):
            raise ValueError("备份目录须与照片位置分离，不能是其自身、父目录或子目录。")
        return
    if options.output is None or not str(options.output).strip():
        raise ValueError("请选择输出目录。")
    output = options.output.resolve(strict=False)
    if base is not None and (base == output or base in output.parents or output in base.parents):
        raise ValueError("输出目录须与照片位置分离，不能是其自身、父目录或子目录。")


def scan_photos(folder: Path) -> list[tuple[Path, Path]]:
    found: list[tuple[Path, Path]] = []
    for root, dirs, files in os.walk(folder, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(root) / name).is_symlink()]
        for name in files:
            source = Path(root) / name
            if is_supported_photo(source) and not source.is_symlink():
                found.append((source, source.relative_to(folder)))
    found.sort(key=lambda pair: str(pair[1]).casefold())
    return found


def collect_photos(options: Options) -> tuple[Path | None, tuple[PhotoEntry, ...]]:
    """返回 (相对路径基准目录或 None, 待处理照片)。文件清单优先于目录。"""
    if options.files:
        paths: list[Path] = []
        seen: set[str] = set()
        for raw in options.files:
            item = Path(raw)
            if item.is_symlink() or not item.is_file():
                raise ValueError(f"照片不存在或不是普通文件：{item.name}")
            if not is_supported_photo(item):
                raise ValueError(f"不支持的格式（{item.suffix}）：{item.name}。支持 {SUFFIX_LABEL}。")
            key = str(item.resolve()).casefold()
            if key in seen:
                continue
            seen.add(key)
            paths.append(item.resolve())
        if not paths:
            raise ValueError("没有可用的照片。")
        root = common_root(paths)
        entries: list[PhotoEntry] = []
        used: set[str] = set()
        for item in paths:
            relative = item.relative_to(root) if root is not None else Path(item.name)
            key = str(relative).casefold()
            if key in used:
                raise ValueError(f"导入的照片存在同名相对路径：{relative}。请分开处理。")
            used.add(key)
            entries.append(PhotoEntry(item, relative))
        entries.sort(key=lambda entry: str(entry.relative).casefold())
        return root, tuple(entries)
    if options.photos is None or not options.photos.is_dir():
        raise ValueError("照片目录不存在。")
    scanned = scan_photos(options.photos)
    return options.photos, tuple(PhotoEntry(source, relative) for source, relative in scanned)


def load_tracks(options: Options, password: str, labels: dict[str, str] | None = None) -> tuple[TrackSource, ...]:
    """读取全部被勾选的轨迹，并在需要时把它们合并成一条曲线。

    标签用于界面显示，缺省用 CLP 文件名。
    这就是第二步（插值成曲线）的入口：手机端只给出第一步的节点，曲线在这里生成。
    """
    labels = labels or {}
    loaded: list[tuple[Path, str, Track]] = []
    for path in options.tracks:
        item = Path(path)
        track: Track = read_clp(item, password)
        label = labels.get(item.stem) or labels.get(str(path)) or item.stem[:8]
        loaded.append((item, label, track))
    if not options.merge_tracks:
        return tuple(
            TrackSource(path, label, build_track_index(track.points, mode=track.mode))
            for path, label, track in loaded
        )
    return (merge_sources(loaded),)


def merge_sources(loaded: Sequence[tuple[Path, str, Track]]) -> TrackSource:
    """把多条连续轨迹的节点按时间串成一条曲线。

    单点补录（mode=single）不参与合并：它的语义是「位置对任意时刻成立」，
    塞进时间序列曲线没有意义。段与段之间的空档不特殊处理，仍由
    MAX_INTERPOLATION_GAP_MS 规则决定是否标为长间隔估算。
    """
    continuous = [(path, label, track) for path, label, track in loaded
                  if track.mode == "track" and track.points]
    skipped = len(loaded) - len(continuous)
    if not continuous:
        raise ValueError("合并模式需要至少一条连续轨迹；单点补录不能参与合并。")
    continuous.sort(key=lambda item: item[2].points[0].t)
    merged: dict[int, TrackPoint] = {}
    for _path, _label, track in continuous:
        for point in track.points:
            current = merged.get(point.t)
            if current is None:
                merged[point.t] = point
            elif point.hacc is not None and (current.hacc is None or point.hacc < current.hacc):
                merged[point.t] = point
    points = [merged[t] for t in sorted(merged)]
    if len(points) < 2:
        raise ValueError("合并后不足两个定位节点，无法生成曲线。")
    label = f"合并的 {len(continuous)} 条轨迹"
    if skipped:
        label += f"（已排除 {skipped} 条单点补录）"
    base = continuous[0][0]
    return TrackSource(base, label, build_track_index(points, mode="track"))


def track_lines(sources: Sequence[TrackSource], *, max_points: int = 4000, max_total: int = 12000) -> tuple[dict, ...]:
    """把本次使用的曲线转成折线，供界面在地图上画轨迹。

    点序即时间序。单条最多 max_points 点，全部合计不超过 max_total 点，超出按等间隔抽稀，
    免得把上千个点塞进界面载荷。
    """
    lines: list[dict] = []
    budget = max_total
    for source in sources:
        points = source.index.points
        if not points or budget <= 0:
            continue
        step = max(1, -(-len(points) // max(1, min(max_points, budget))))
        picked = points[::step]
        budget -= len(picked)
        lines.append({"label": source.label, "points": [[p.lat, p.lon] for p in picked]})
    return tuple(lines)


def _match_key(match: Match, order: int) -> tuple:
    """越小越优：先比时间证据强度，再比夹逼跨度，再比两端精度，最后用勾选顺序稳定排序。"""
    tier = MATCH_PRIORITY.get(match.method, 9)
    span = (match.source_after_ms - match.source_before_ms) if match.source_after_ms is not None else 0
    hacc = match.point.hacc if match.point.hacc is not None else float("inf")
    return (tier, span, hacc, order)


def pick_track(
    sources: Sequence[TrackSource], capture_ms: int
) -> tuple[TrackSource, Match, int] | None:
    """在多条轨迹里为一张照片选最合适的一条。返回 (轨迹, 匹配, 候选数)。"""
    best: tuple[tuple, TrackSource, Match] | None = None
    count = 0
    for order, source in enumerate(sources):
        try:
            match = match_track(source.index, capture_ms)
        except MatchError:
            continue
        if match is None:
            continue
        count += 1
        key = _match_key(match, order)
        if best is None or key < best[0]:
            best = (key, source, match)
    if best is None:
        return None
    return best[1], best[2], count


def describe_match(match: Match, candidates: int) -> str:
    text = METHOD_TEXT.get(match.method, match.method)
    if match.method in ("interpolated", "curve-long-gap") and match.source_after_ms is not None:
        gap = (match.source_after_ms - match.source_before_ms) / 1000
        text += f"（前后间隔 {gap:.0f} 秒）"
    elif match.method == "single":
        text += "，时间采用照片拍摄时间"
    if candidates > 1:
        text += f" · 在 {candidates} 条轨迹中择优"
    return text


def prepare_plan(
    options: Options, password: str, exiftool: ExifTool,
    progress: Callable[[int, int, PlanRow], None] | None = None,
    stop: Event | None = None,
    labels: dict[str, str] | None = None,
) -> Plan:
    validate_paths(options)
    sources = load_tracks(options, password, labels)
    root, entries = collect_photos(options)
    usable = any(source.index.points for source in sources)
    rows: list[PlanRow] = []
    destination_label = "原片" if options.in_place else "副本"
    for index, entry in enumerate(entries, 1):
        if stop is not None and stop.is_set():
            raise InterruptedError("用户停止预览")
        source, relative = entry.source, entry.relative
        stat = source.stat()
        capture_ms = None
        offset_used = ""
        match = None
        status = "skip"
        reason = ""
        existing_position = False
        has_gps_ifd = False
        track_label = ""
        try:
            # 只有副本模式需要担心同名输出；就地模式的写入目标就是原片本身。
            if (not options.in_place and options.output is not None
                    and (options.output / relative).exists()):
                reason = "输出文件已存在"
            else:
                meta = exiftool.metadata(source)
                if not file_type_ok(source, meta.get("File:FileType")):
                    seen_type = meta.get("File:FileType") or "空"
                    reason = f"扩展名与文件内容不符（读到 {seen_type}）"
                else:
                    # 只看有没有真的经纬度/海拔：空 GPS IFD 不算已有定位，不该拦住补录。
                    existing_position = exiftool.has_existing_position(meta)
                    has_gps_ifd = exiftool.has_existing_gps(meta)
                    if existing_position and not options.overwrite_existing_gps:
                        reason = "照片已有经纬度或海拔，未勾选覆盖，保留原件"
                    else:
                        capture_ms, offset_used = capture_utc_ms(
                            meta, options.default_offset, options.correction_seconds
                        )
                        picked = pick_track(sources, capture_ms)
                        if picked is not None:
                            chosen, match, candidates = picked
                            status = "ready"
                            track_label = chosen.label
                            reason = describe_match(match, candidates)
                            if existing_position:
                                reason = f"覆盖已有定位（写入{destination_label}）· " + reason
                            elif has_gps_ifd:
                                reason = f"可写入{destination_label}（原 GPS 标签无定位数据）· " + reason
                            else:
                                reason = f"可写入{destination_label} · " + reason
                        elif not usable:
                            reason = "所选轨迹没有可用定位点（水平精度需不超过 100 米）"
                        else:
                            reason = "所选轨迹的时间范围都未覆盖曝光时刻"
        except (OSError, MatchError, ValueError, RuntimeError) as exc:
            reason = str(exc)
        row = PlanRow(source, relative, stat.st_size, stat.st_mtime_ns,
                      capture_ms, offset_used, match, status, reason, index,
                      existing_position, has_gps_ifd, track_label)
        rows.append(row)
        if progress:
            progress(index, len(entries), row)
    return Plan(options, len(sources), tuple(rows), root, track_lines(sources))


def _stage_photo(source: Path, row: PlanRow, exiftool: ExifTool, target_dir: Path,
                 options: Options) -> Path:
    """在目标目录旁生成临时副本，写入 GPS 并读回验证；失败时自行清理。"""
    stage = target_dir / f".{source.stem}.clp-{uuid.uuid4().hex}{source.suffix}"
    shutil.copy2(source, stage)
    try:
        stage_meta = exiftool.metadata(stage)
        if not file_type_ok(stage, stage_meta.get("File:FileType")):
            raise ValueError("副本的格式与扩展名不符，已停止写入")
        if exiftool.has_existing_position(stage_meta):
            if not options.overwrite_existing_gps or not row.existing_position:
                raise ValueError("副本发现未获准覆盖的已有定位")
            exiftool.clear_gps(stage)
        if row.capture_ms is None:
            raise ValueError("缺少照片拍摄时间")
        photo_gps = replace(row.match.point, t=row.capture_ms)
        exiftool.write_gps(stage, photo_gps)
        exiftool.verify_gps(stage, photo_gps)
        return stage
    except BaseException:
        stage.unlink(missing_ok=True)
        raise


def execute_plan(
    plan: Plan, exiftool: ExifTool,
    progress: Callable[[int, int, AuditRow], None] | None = None,
    stop: Event | None = None,
) -> tuple[AuditRow, ...]:
    """执行写入并返回逐张结果；不生成表格文件。"""
    validate_paths(plan.options)
    options = plan.options
    if not options.in_place and options.output is not None:
        options.output.mkdir(parents=True, exist_ok=True)
    results: list[AuditRow] = []
    for index, row in enumerate(plan.rows, 1):
        destination: Path | None = None
        latitude = longitude = altitude = None
        if stop is not None and stop.is_set():
            item = AuditRow(row, "cancelled", "用户停止", None)
        elif row.status != "ready" or row.match is None:
            item = AuditRow(row, "skipped", row.reason, None)
        else:
            stage: Path | None = None
            try:
                current = row.source.stat()
                if current.st_size != row.size or current.st_mtime_ns != row.mtime_ns:
                    raise ValueError("源照片自预览后发生变化")
                if options.in_place:
                    stage = _stage_photo(row.source, row, exiftool, row.source.parent, options)
                    if options.output is not None:
                        # 备份必须在替换之前，复制的仍是改写前的原片。
                        backup = options.output / row.relative
                        if backup.exists():
                            raise FileExistsError(f"备份文件已存在，未改写原片：{backup.name}")
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(row.source, backup)
                    os.replace(stage, row.source)
                    stage = None
                    destination = row.source
                else:
                    output = options.output
                    if output is None:
                        raise ValueError("请选择输出目录。")
                    destination = output / row.relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if output.resolve() not in destination.parent.resolve().parents and destination.parent.resolve() != output.resolve():
                        raise ValueError("输出子目录指向了输出目录外")
                    if destination.exists():
                        raise FileExistsError("输出文件已存在，未覆盖")
                    stage = _stage_photo(row.source, row, exiftool, destination.parent, options)
                    # Windows 上若目标在此期间出现，os.rename 会失败而不是静默覆盖。
                    os.rename(stage, destination)
                    stage = None
                written = replace(row.match.point, t=row.capture_ms)
                latitude, longitude, altitude = written.lat, written.lon, written.alt
                detail = "旧定位已替换且读回验证" if row.existing_position else "GPS IFD 已读回验证"
                if options.in_place:
                    detail += " · 原片已就地改写"
                item = AuditRow(row, "written", detail, destination, latitude, longitude, altitude)
            except FileExistsError as exc:
                item = AuditRow(row, "skipped", str(exc), None)
            except (OSError, ValueError, RuntimeError) as exc:
                item = AuditRow(row, "error", str(exc), None)
            finally:
                if stage is not None:
                    stage.unlink(missing_ok=True)
        results.append(item)
        if progress:
            progress(index, len(plan.rows), item)
    return tuple(results)
