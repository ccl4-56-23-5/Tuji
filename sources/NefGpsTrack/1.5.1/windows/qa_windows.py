"""Interoperability and copy-only NEF integration checks (never edits --sample)."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from batch import Options, execute_plan, load_tracks, prepare_plan
from clp_codec import TrackPoint
from exiftool_io import SUPPORTED_SUFFIXES, file_type_ok
from clp_codec import ClpError, decrypt_clp, encrypt_clp
from exiftool_io import ExifTool

ROOT = Path(__file__).resolve().parents[1]
from time_match import build_track_index, capture_utc_ms, match_track


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--expected-utc-ms", type=int, default=1780996514370, help="Independently verified sample capture timestamp")
    parser.add_argument("--exiftool", type=Path, required=True)
    parser.add_argument("--temp", type=Path, required=True)
    args = parser.parse_args()
    args.temp.mkdir(parents=True, exist_ok=True)

    vector_path = Path(__file__).resolve().parents[1] / "qa" / "clp1_test_vector.json"
    vector = json.loads(vector_path.read_text(encoding="utf-8"))
    vector_blob = bytes.fromhex(vector["clpHex"])
    track = decrypt_clp(vector_blob, vector["password"])
    check(len(track.points) == 2 and track.points[0].lat == 0.0, "CLP 公共向量解密失败")
    plain = json.loads(vector["plaintextUtf8"])
    regenerated = encrypt_clp(
        plain, vector["password"],
        salt=bytes.fromhex(vector["saltHex"]), nonce=bytes.fromhex(vector["nonceHex"]),
    )
    check(regenerated == vector_blob, "CLP 公共向量加密字节不一致")
    for changed, password in ((vector_blob, "wrong"), (vector_blob[:36] + bytes([vector_blob[36] ^ 1]) + vector_blob[37:], vector["password"])):
        try:
            decrypt_clp(changed, password)
        except ClpError:
            pass
        else:
            raise AssertionError("CLP 错误密码/篡改未被拒绝")

    exif = ExifTool(args.exiftool)
    original_hash = sha256(args.sample)
    original_meta = exif.metadata(args.sample)
    check(exif.has_existing_gps(original_meta), "样本 GPS IFD 未读到")
    capture_ms, used_offset = capture_utc_ms(original_meta, "+08:00", 0)
    check(used_offset == "+08:00", "样本相机时区读取失败")
    check(capture_ms == args.expected_utc_ms, "样本拍摄时间解析失败")

    with tempfile.TemporaryDirectory(prefix="qa-", dir=args.temp) as temp_name:
        temp = Path(temp_name)
        password = "QA-only-测试"
        points = [
            {"t": capture_ms - 30_000, "lat": 36.1, "lon": 103.8,
             "alt": 1000.0, "hacc": 10.0, "speed": None, "bearing": None, "provider": "gps"},
            {"t": capture_ms + 30_000, "lat": 36.2, "lon": 103.9,
             "alt": 1002.0, "hacc": 15.0, "speed": None, "bearing": None, "provider": "gps"},
        ]
        payload = {"schema": "nef-gps-track/1", "createdUtcMs": capture_ms + 60_000, "points": points}
        clp = temp / "qa.clp"
        clp.write_bytes(encrypt_clp(payload, password))
        track_index = build_track_index(decrypt_clp(clp.read_bytes(), password).points)
        matched = match_track(track_index, capture_ms)
        check(matched is not None and matched.method == "interpolated", "120 秒插值失败")
        check(abs(matched.point.lat - 36.15) < 1e-9 and abs(matched.point.alt - 1001.0) < 1e-9,
              "轨迹插值数值错误")
        check(match_track(track_index, capture_ms + 200_000) is None,
              "过期点未拒绝")

        existing_input = temp / "existing"
        existing_input.mkdir()
        existing = existing_input / args.sample.name
        shutil.copy2(args.sample, existing)
        existing_hash = sha256(existing)
        no_overwrite = Options((clp,), existing_input, (), temp / "out-skip", "+08:00", 0, False)
        skip_plan = prepare_plan(no_overwrite, password, exif)
        check(len(skip_plan.rows) == 1 and skip_plan.rows[0].status == "skip", "默认未跳过已有GPS")
        check("已有经纬度或海拔" in skip_plan.rows[0].reason, "跳过原因不正确")
        check(skip_plan.rows[0].existing_position and skip_plan.rows[0].has_gps_ifd,
              "已有定位的判定标记不正确")
        check(skip_plan.rows[0].number == 1, "预览结果没有编号")

        # 只有 GPS 版本/日期这类空 GPS IFD，不含经纬度海拔：不该拦住补录
        stub_input = temp / "gps-stub"
        stub_input.mkdir()
        stub = stub_input / args.sample.name
        shutil.copy2(args.sample, stub)
        exif._run(["-overwrite_original", "-P", "-GPS:all=",
                   "-GPS:GPSVersionID=2 3 0 0", "-GPS:GPSDateStamp=2026:10:03", str(stub)], timeout=180)
        stub_meta = exif.metadata(stub)
        check(exif.has_existing_gps(stub_meta), "空 GPS IFD 夹具没有 GPS 标签")
        check(not exif.has_existing_position(stub_meta), "空 GPS IFD 被判成了已有定位")
        stub_plan = prepare_plan(Options((clp,), stub_input, (), temp / "out-stub", "+08:00", 0, False),
                                 password, exif)
        check(stub_plan.rows[0].status == "ready",
              f"空 GPS IFD 仍然拦住了补录：{stub_plan.rows[0].reason}")
        check("原 GPS 标签无定位数据" in stub_plan.rows[0].reason, "空 GPS IFD 的写入说明不正确")
        stub_rows = execute_plan(stub_plan, exif)
        check(stub_rows[0].result == "written", f"空 GPS IFD 的照片写入失败：{stub_rows[0].detail}")
        stub_written = exif.metadata(stub_rows[0].destination, numeric=True)
        check(abs(float(stub_written["GPS:GPSLatitude"]) - 36.15) < 1e-6,
              "空 GPS IFD 的照片没有写入正确纬度")
        check("GPS:GPSSatellites" not in stub_written, "空 GPS IFD 的照片残留了未测得的标签")

        overwrite = Options((clp,), existing_input, (), temp / "out-overwrite", "+08:00", 0, True)
        overwrite_plan = prepare_plan(overwrite, password, exif)
        check(overwrite_plan.rows[0].status == "ready", "覆盖选项未允许复制写入")
        audit1 = execute_plan(overwrite_plan, exif)
        results1 = audit1
        check(results1[0].result == "written", f"覆盖副本失败：{results1[0].detail}")
        check(abs(results1[0].latitude - 36.15) < 1e-6 and results1[0].altitude is not None
              and abs(results1[0].altitude - 1001.0) < 1e-6, "写入结果未回传经纬度与海拔")
        check(sha256(existing) == existing_hash, "输入照片被修改")
        replaced_meta = exif.metadata(results1[0].destination, numeric=True)
        check("GPS:GPSSatellites" not in replaced_meta, "旧卫星占位未清除")
        check(abs(float(replaced_meta["GPS:GPSLatitude"]) - 36.15) < 1e-6,
              "覆盖后的 GPS 纬度不正确")

        missing_input = temp / "missing"
        missing_input.mkdir()
        missing = missing_input / args.sample.name
        shutil.copy2(args.sample, missing)
        exif.clear_gps(missing)  # Only a temporary copy is modified.
        missing_hash = sha256(missing)
        check(not exif.has_existing_gps(exif.metadata(missing)), "临时副本 GPS 未清空")
        normal = Options((clp,), missing_input, (), temp / "out-normal", "+08:00", 0, False)
        normal_plan = prepare_plan(normal, password, exif)
        check(normal_plan.rows[0].status == "ready", "无 GPS 的 NEF 未进入可写队列")
        results2 = execute_plan(normal_plan, exif)
        check(results2[0].result == "written", f"无 GPS 副本写入失败：{results2[0].detail}")
        check(sha256(missing) == missing_hash, "无 GPS 的输入副本被修改")
        check(prepare_plan(normal, password, exif).rows[0].status == "skip", "已有输出未跳过")

        bad_payload = {**payload, "points": [{**points[0], "hacc": 101.0}]}
        low_clp = temp / "low.clp"
        low_clp.write_bytes(encrypt_clp(bad_payload, password))
        low_options = Options((low_clp,), missing_input, (), temp / "out-low", "+08:00", 0, False)
        low_plan = prepare_plan(low_options, password, exif)
        check(low_plan.rows[0].status == "skip" and "精度" in low_plan.rows[0].reason,
              "低精度点未拒绝")

        # 就地改写：只改临时副本，并核对备份确实是改写前的原片
        inplace_input = temp / "inplace"
        inplace_input.mkdir()
        inplace_photo = inplace_input / args.sample.name
        shutil.copy2(args.sample, inplace_photo)
        before_inplace = sha256(inplace_photo)
        backup_dir = temp / "backup"
        inplace = Options((clp,), None, (inplace_photo,), backup_dir, "+08:00", 0, True, True)
        inplace_plan = prepare_plan(inplace, password, exif)
        check(inplace_plan.rows[0].status == "ready", "就地改写未进入可写队列")
        inplace_rows = execute_plan(inplace_plan, exif)
        check(inplace_rows[0].result == "written", f"就地改写失败：{inplace_rows[0].detail}")
        check(sha256(inplace_photo) != before_inplace, "就地改写未修改原片")
        check(abs(inplace_rows[0].latitude - 36.15) < 1e-6
              and inplace_rows[0].altitude is not None
              and abs(inplace_rows[0].altitude - 1001.0) < 1e-6, "就地改写未回传坐标")
        backup = backup_dir / args.sample.name
        check(backup.is_file() and sha256(backup) == before_inplace, "备份不是改写前的原片")
        inplace_meta = exif.metadata(inplace_photo, numeric=True)
        check(abs(float(inplace_meta["GPS:GPSLatitude"]) - 36.15) < 1e-6, "就地改写后的原片 GPS 不正确")
        again = Options((clp,), None, (inplace_photo,), None, "+08:00", 0, False, True)
        check(prepare_plan(again, password, exif).rows[0].status == "skip",
              "就地改写未拒绝未获准覆盖的已有 GPS")

        # 备份目录留空时也应能就地改写
        bare_input = temp / "inplace-bare"
        bare_input.mkdir()
        bare_photo = bare_input / args.sample.name
        shutil.copy2(missing, bare_photo)
        bare = Options((clp,), None, (bare_photo,), None, "+08:00", 0, False, True)
        bare_plan = prepare_plan(bare, password, exif)
        check(bare_plan.rows[0].status == "ready", "无备份目录的就地改写未进入队列")
        bare_rows = execute_plan(bare_plan, exif)
        check(bare_rows[0].result == "written", f"无备份就地改写失败：{bare_rows[0].detail}")

        check(not list(temp.rglob("*.csv")), "写入过程生成了表格文件")

        # 多轨迹择优：先比时间证据强度，再比夹逼跨度
        multi_input = temp / "multi"
        multi_input.mkdir()
        multi_photo = multi_input / args.sample.name
        shutil.copy2(args.sample, multi_photo)

        def track_file(name, span_ms, offset_ms=0):
            path = temp / name
            path.write_bytes(encrypt_clp({**payload, "points": [
                {**points[0], "t": capture_ms + offset_ms - span_ms // 2},
                {**points[1], "t": capture_ms + offset_ms + span_ms // 2},
            ]}, password))
            return path

        tight_clp = track_file("tight.clp", 60_000)          # 前后60秒 → 曲线插值
        near_clp = track_file("near.clp", 600_000)           # 前后600秒 → 长间隔估算
        wide_clp = track_file("wide.clp", 3_600_000)         # 跨度更大，同档位
        far_clp = track_file("far.clp", 600_000, 7_200_000)  # 完全不在时间范围内
        lone_clp = temp / "lone.clp"
        lone_clp.write_bytes(encrypt_clp(
            {**payload, "mode": "single", "points": [{**points[0], "t": capture_ms + 3_600_000}]}, password))
        labels = {p.stem: n for p, n in ((tight_clp, "紧轨迹"), (near_clp, "近轨迹"),
                                         (wide_clp, "宽轨迹"), (far_clp, "远轨迹"), (lone_clp, "单点"))}

        def pick(tracks, out_name):
            options = Options(tuple(tracks), None, (multi_photo,), temp / out_name, "+08:00", 0, True)
            return prepare_plan(options, password, exif, labels=labels).rows[0]

        only_near = pick((far_clp, near_clp), "out-m1")
        check(only_near.status == "ready", f"多轨迹未进入可写队列：{only_near.reason}")
        check(only_near.track_label == "近轨迹", f"唯一命中未被选中：{only_near.track_label}")

        tier = pick((near_clp, tight_clp), "out-m2")
        check(tier.track_label == "紧轨迹",
              f"档位高的轨迹没有胜出（曲线插值应优于长间隔估算）：{tier.track_label}")
        check("曲线插值（前后间隔 60 秒）" in tier.reason, f"匹配说明不正确：{tier.reason}")

        span = pick((wide_clp, near_clp), "out-m3")
        check(span.track_label == "近轨迹", f"同档位未选跨度更小的轨迹：{span.track_label}")
        check("择优" in span.reason, f"多候选时未说明候选数：{span.reason}")

        beats_single = pick((lone_clp, near_clp), "out-m4")
        check(beats_single.track_label == "近轨迹", f"单点压过了覆盖轨迹：{beats_single.track_label}")

        out_of_range = pick((far_clp, lone_clp), "out-m5")
        check(out_of_range.track_label == "单点",
              f"时间范围外未回退到单点：{out_of_range.track_label} / {out_of_range.reason}")

        # 多格式：DNG/JPG/PNG/HEIC 与 NEF 走同一条写入→读回→清理链路
        fixtures = sorted((ROOT / "qa" / "formats").iterdir())
        formats = [f for f in fixtures if f.suffix.lower() in SUPPORTED_SUFFIXES]
        check(len(formats) >= 4, f"qa/formats 夹具不足：{[f.name for f in fixtures]}")
        fmt_root = temp / "formats"
        fmt_root.mkdir()
        for fixture in formats:
            target = fmt_root / fixture.name
            shutil.copy2(fixture, target)
            fmt_meta = exif.metadata(target)
            check(file_type_ok(target, fmt_meta.get("File:FileType")),
                  f"{fixture.name} 的 FileType 与扩展名不符：{fmt_meta.get('File:FileType')}")
            check(not exif.has_existing_position(fmt_meta), f"{fixture.name} 夹具自带定位")
            point = TrackPoint(capture_ms, 36.153, 103.857, 1001.0, 6.0, None, None, "curve")
            exif.write_gps(target, point)
            exif.verify_gps(target, point)
            check(exif.has_existing_position(exif.metadata(target)), f"{fixture.name} 写入后读不到定位")
            exif.clear_gps(target)
            check(not exif.has_existing_position(exif.metadata(target)), f"{fixture.name} 清理不干净")
        check(not exif.has_existing_position(exif.metadata(formats[0])),
              "夹具被写脏了——它必须是只读证据")
        # 文件清单优先于目录，且相对路径以公共父目录为基准
        list_plan = prepare_plan(Options((near_clp,), multi_input, (multi_photo,), temp / "out-list", "+08:00", 0, True),
                                 password, exif, labels=labels)
        check([str(r.relative) for r in list_plan.rows] == [args.sample.name],
              f"文件清单的相对路径不正确：{[str(r.relative) for r in list_plan.rows]}")
        check(list_plan.photo_root == multi_input, "文件清单的相对路径基准不正确")
        # 勾选零条轨迹必须被拒绝
        try:
            prepare_plan(Options((), multi_input, (), temp / "out-none", "+08:00", 0, True), password, exif)
        except ValueError as exc:
            check("轨迹" in str(exc), f"零轨迹的报错不明确：{exc}")
        else:
            raise AssertionError("零轨迹未被拒绝")

        # 合并模式：多条连续轨迹串成一条曲线，单点被排除
        def merge_pick(tracks, out_name):
            options = Options(tuple(tracks), None, (multi_photo,), temp / out_name,
                              "+08:00", 0, True, False, True)
            plan = prepare_plan(options, password, exif, labels=labels)
            return plan, plan.rows[0]

        def merged_track(tracks):
            options = Options(tuple(tracks), None, (), None, "+08:00", 0, True, False, True)
            return load_tracks(options, password, labels)

        merged_plan, merged_row = merge_pick((far_clp, near_clp), "out-merge")
        check(merged_plan.track_count == 1, f"合并后应只有一条曲线，实际 {merged_plan.track_count}")
        check(merged_row.track_label.startswith("合并的 2 条轨迹"),
              f"合并标签不正确：{merged_row.track_label}")
        check(merged_row.status == "ready", f"合并后未进入可写队列：{merged_row.reason}")
        check("长间隔估算" in merged_row.reason or "曲线插值" in merged_row.reason,
              f"合并后匹配说明不正确：{merged_row.reason}")
        sources = merged_track((far_clp, near_clp))
        check(len(sources) == 1, "合并没有收敛成一条曲线")
        index = sources[0].index
        check(index.times == tuple(sorted(index.times)), "合并后节点没有按时间升序")
        check(index.times[0] == capture_ms - 300_000,
              f"合并后首个节点不是最早那段的首点：{index.times[0]}")
        check(index.times[-1] == capture_ms + 7_200_000 + 300_000,
              f"合并后末个节点不是最晚那段的末点：{index.times[-1]}")
        check(match_track(index, capture_ms) is not None, "合并后覆盖不到原拍摄时刻")
        check(match_track(index, index.times[-1] + 1) is None, "合并后仍对时间范围外外推")
        check(match_track(index, index.times[0] - 1) is None, "合并后仍对时间范围外外推")
        _merged_single_plan, merged_single_row = merge_pick((lone_clp, near_clp), "out-merge-2")
        check("已排除 1 条单点补录" in merged_single_row.track_label,
              f"单点未被排除或未提示：{merged_single_row.track_label}")
        try:
            merge_pick((lone_clp,), "out-merge-3")
        except ValueError as exc:
            check("单点" in str(exc), f"全单点合并的报错不明确：{exc}")
        else:
            raise AssertionError("只有单点补录时合并未被拒绝")
        # 各自成曲线时不合并
        separate = load_tracks(Options((far_clp, near_clp), None, (), None, "+08:00", 0, True),
                               password, labels)
        check(len(separate) == 2, "未开启合并时不应收敛成一条曲线")

        # 编号与轨迹折线：界面据此在地图上按编号插图钉
        check([r.number for r in merged_plan.rows] == [1], "合并预览的编号不正确")
        lines = merged_plan.track_lines
        check(len(lines) == 1, f"合并模式应给出一条折线，实际 {len(lines)}")
        check(lines[0]["label"].startswith("合并的"), f"折线标签不正确：{lines[0]['label']}")
        check(all(len(pair) == 2 for pair in lines[0]["points"]), "折线点不是 [lat, lon]")
        check(len(lines[0]["points"]) >= 2, "折线点太少")
        check(len(lines[0]["points"]) <= 4000, "折线点数超出上限")
        # 大轨迹会被抽稀，但必须保留首末点与时间顺序
        long_clp = temp / "long.clp"
        long_points = [dict(points[0], t=capture_ms - 600_000 + i * 1000, lat=36.15 + i * 1e-5, alt=1000.0)
                       for i in range(5000)]
        long_clp.write_bytes(encrypt_clp({**payload, "points": long_points}, password))
        long_plan = prepare_plan(Options((long_clp,), None, (multi_photo,), temp / "out-long",
                                         "+08:00", 0, True), password, exif, labels={long_clp.stem: "长轨迹"})
        long_line = long_plan.track_lines[0]["points"]
        check(1000 <= len(long_line) <= 4000, f"长轨迹折线抽稀后点数不合理：{len(long_line)}")
        check(long_line == sorted(long_line), "折线点没有按时间顺序")
        separate_plan = prepare_plan(Options((far_clp, near_clp), None, (multi_photo,), temp / "out-lines",
                                             "+08:00", 0, True), password, exif, labels=labels)
        check(len(separate_plan.track_lines) == 2, "各自成曲线时应给出两条折线")
        check([r.number for r in separate_plan.rows] == [1], "预览编号应从 1 起且连续")
        ready = [r.number for r in separate_plan.rows if r.status == "ready" and r.match is not None]
        check(ready == [1], f"可写照片的编号不正确：{ready}")
        check(all(pair[0] is not None for pair in separate_plan.track_lines[0]["points"]), "折线点含空值")

    check(sha256(args.sample) == original_hash, "用户原始样本哈希变化")
    print(json.dumps({
        "status": "passed", "exiftool": exif.version(), "sampleSha256": original_hash,
        "captureUtcMs": capture_ms,
        "checks": ["CLP vector and tamper", "sample exposure time", "interpolation and stale",
                   "default existing-GPS skip", "copy-only overwrite and readback",
                   "missing-GPS copy write and readback", "output collision", "low accuracy",
                   "written coordinates returned", "in-place rewrite with pre-write backup",
                   "in-place without backup", "in-place rejects unapproved existing position",
                   "no table file produced",
                   "empty GPS IFD no longer blocks a write",
                   "photos with a real position stay untouched unless overwrite is checked",
                   "preview numbers every photo from one",
                   "preview returns one map pin per matched photo",
                   "track polylines are returned in time order and decimated",
                   "multi-track picks the only covering track",
                   "higher evidence tier beats a shorter span",
                   "shorter span wins inside the same tier",
                   "covering track outranks single point", "falls back to single point out of range",
                   "photo file list overrides folder and keeps relative paths",
                   "empty track selection rejected",
                   "merge joins several tracks into one curve",
                   "merge keeps nodes time-ordered and never extrapolates",
                   "merge excludes single-point tracks and says so",
                   "merge rejects a selection of single-point tracks only",
                   "separate mode keeps one curve per track",
                   "every supported format writes, verifies and clears",
                   "original sample unchanged"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
