"""路径库：把 CLP 存在数据目录的「路径库」文件夹里，用可读文件名。

1.5.0 起：
- 位置是 `<安装路径>\\data\\路径库\\`（见 paths.py），不再写 %LOCALAPPDATA%；
- 文件名按内容命名，形如 `2026-09-24_1355_连续_115点.clp`，方便用户直接看懂、直接拷走；
  界面与进程之间传的轨迹标识就是这个文件名去掉扩展名；
- 旧版遗留的 32 位十六进制文件名会在启动时按内容改成可读名（是改名，不是删除）。
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from clp_codec import FIXED_KEY, _key, _parse_payload, decrypt_clp, encrypt_clp
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from smoothing import build_curves

import paths

LEGACY_STEM = re.compile(r"^[0-9a-f]{32}$")
FORBIDDEN = set('\\/:*?"<>|')


def readable_stem(payload: dict, taken: set[str] | None = None) -> str:
    """按 CLP 内容起一个可读文件名（不含扩展名），重名追加 _2、_3。"""
    taken = {name.lower() for name in (taken or set())}
    points = payload.get("points") or []
    started = points[0]["t"] if points else payload.get("createdUtcMs", 0)
    stamp = time.localtime(int(started) / 1000)
    mode = "单点" if payload.get("mode") == "single" else "连续"
    base = f"{time.strftime('%Y-%m-%d_%H%M', stamp)}_{mode}_{len(points)}点"
    candidate, index = base, 2
    while candidate.lower() in taken:
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def safe_stem(value) -> str:
    """校验界面传回的轨迹标识：只能是文件名，不能带任何路径成分。"""
    if not isinstance(value, str):
        raise ValueError("无效的轨迹标识")
    stem = value.strip()
    if not stem or stem in (".", ".."):
        raise ValueError("无效的轨迹标识")
    if any(ch in stem for ch in FORBIDDEN):
        raise ValueError("轨迹标识不能包含路径字符")
    if len(stem) > 120:
        raise ValueError("轨迹标识过长")
    return stem


class Library:
    def __init__(self, root=None):
        self.root = Path(root) if root else paths.routes_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.cache = {}

    # ---------------------------------------------------------------- 定位
    def path(self, id):
        stem = safe_stem(id)
        candidate = (self.root / f"{stem}.clp").resolve()
        if candidate.parent != self.root.resolve():
            raise ValueError("轨迹标识越界")
        return self.root / f"{stem}.clp"

    def _taken(self, extra: str = "") -> set[str]:
        names = {p.stem for p in self.root.glob("*.clp")}
        if extra:
            names.add(extra)
        return names

    # ---------------------------------------------------------------- 读取
    def _decode(self, blob):
        decrypt_clp(blob, FIXED_KEY)
        data = json.loads(AESGCM(_key(FIXED_KEY, blob[8:24])).decrypt(blob[24:36], blob[36:], blob[:36]))
        if "rawPoints" in data:
            _parse_payload(json.dumps(dict(data, points=data["rawPoints"])).encode())
            if len(data["points"]) != len(data["rawPoints"]) or any(
                    a["t"] != b["t"] for a, b in zip(data["points"], data["rawPoints"])):
                raise ValueError("原始点与平滑点时间不一致")
        return build_curves(data)

    def load(self, path):
        path = Path(path)
        key = (str(path), path.stat().st_mtime_ns, path.stat().st_size)
        if key in self.cache:
            return self.cache[key]
        result = self._decode(path.read_bytes())
        self.cache = {k: v for k, v in self.cache.items() if k[0] != str(path)}
        self.cache[key] = result
        return result

    # ---------------------------------------------------------------- 写入
    def _store(self, payload):
        stem = readable_stem(payload, taken=self._taken())
        self.path(stem).write_bytes(encrypt_clp(payload, FIXED_KEY))
        return stem

    def import_file(self, path):
        return self._store(self.load(path))

    def import_bytes(self, name, data):
        """导入拖入窗口的 .clp 字节流：走与文件导入完全相同的解密与校验，不落地临时文件。"""
        if not str(name).lower().endswith(".clp"):
            raise ValueError("只支持 .clp 文件")
        if not data:
            raise ValueError("文件内容为空")
        return self._store(self._decode(data))

    # ---------------------------------------------------------------- 旧名改造
    def migrate_readable_names(self) -> dict:
        """把 32 位十六进制命名的历史文件按内容改成可读名。

        目录是「路径库」，用户可能直接往里丢文件，所以这里要能反复安全执行：
        解不开的文件原样留在原地，只统计不处理。
        """
        result = {"renamed": 0, "kept": 0}
        for file in sorted(self.root.glob("*.clp")):
            if not LEGACY_STEM.match(file.stem):
                continue
            try:
                payload = self.load(file)
            except Exception:
                result["kept"] += 1
                continue
            stem = readable_stem(payload, taken=self._taken(extra=file.stem))
            if stem == file.stem:
                continue
            try:
                file.rename(self.path(stem))
                result["renamed"] += 1
            except OSError:
                result["kept"] += 1
        self.cache = {}
        return result

    # ---------------------------------------------------------------- 列表
    def list(self):
        items = []
        for f in sorted(self.root.glob("*.clp")):
            try:
                p = self.load(f)
                ps = p["points"]
                started = ps[0]["t"] if ps else p["createdUtcMs"]
                items.append(dict(id=f.stem, name=f.stem, started=started,
                                  ended=ps[-1]["t"] if ps else p["createdUtcMs"],
                                  count=len(ps), state="saved", mode=p.get("mode", "track")))
            except Exception as e:
                items.append(dict(id=f.stem, name=f.stem, started=int(f.stat().st_mtime * 1000),
                                  ended=None, count=0, state="error", error=str(e)))
        return sorted(items, key=lambda x: x["started"], reverse=True)

    def delete(self, id):
        self.path(id).unlink()

    def export(self, id, path):
        if Path(path).resolve() == self.path(id).resolve():
            return
        shutil.copyfile(self.path(id), path)
