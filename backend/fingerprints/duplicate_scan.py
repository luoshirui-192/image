"""Pre-import scan for duplicate files inside a batmatch zip / extract tree."""
from __future__ import annotations

import hashlib
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from utils.path_builder import normalize_suffix

# Kind buckets for reporting
KIND_BMP = "bmp"
KIND_TEMPLATE = "template"
KIND_OTHER = "other"

TYPE_ZIP_DUPLICATE_CONTENT = "zip_duplicate_content"
TYPE_ZIP_NAME_COLLISION = "zip_name_collision"
TYPE_PAIR_SAME_BMP = "pair_same_bmp"
TYPE_CROSS_PAIR_SHARED_BMP = "cross_pair_shared_bmp"

# Types that block import when fail_on_duplicates=True
BLOCKING_TYPES = frozenset({TYPE_ZIP_NAME_COLLISION, TYPE_PAIR_SAME_BMP})


def compute_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _file_kind(suffix: str) -> str:
    if suffix == "bmp":
        return KIND_BMP
    if suffix:
        return KIND_TEMPLATE
    return KIND_OTHER


@dataclass
class DuplicateReport:
    warnings: list[dict] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, warning: dict) -> None:
        self.warnings.append(warning)
        wtype = warning.get("type") or "unknown"
        self.counts[wtype] = int(self.counts.get(wtype, 0)) + 1

    @property
    def total(self) -> int:
        return len(self.warnings)

    @property
    def blocking_count(self) -> int:
        return sum(self.counts.get(t, 0) for t in BLOCKING_TYPES)

    def summary_text(self) -> str:
        if not self.warnings:
            return "未发现包内重复"
        parts = [f"{k}={v}" for k, v in sorted(self.counts.items()) if v]
        return f"发现重复 {self.total} 项（{', '.join(parts)}）"

    def to_dict(self) -> dict:
        return {
            "counts": dict(self.counts),
            "total": self.total,
            "blocking_count": self.blocking_count,
            "summary": self.summary_text(),
            "warnings": self.warnings[:200],  # cap payload size
            "truncated": max(0, self.total - min(self.total, 200)),
        }


def scan_zip_name_collisions(zf: zipfile.ZipFile) -> DuplicateReport:
    """
    Detect duplicate member names in the zip (extractall would silently overwrite).
    Compares normalized forward-slash paths, case-sensitive (zip standard).
    """
    report = DuplicateReport()
    seen: dict[str, list[str]] = defaultdict(list)
    for info in zf.infolist():
        if info.is_dir():
            continue
        # Zip may use \\ ; normalize for collision check
        name = info.filename.replace("\\", "/").lstrip("/")
        if not name or name.endswith("/"):
            continue
        key = name
        seen[key].append(info.filename)

    for key, names in sorted(seen.items()):
        # Same key appearing twice in namelist (rare but possible with some tools)
        if len(names) > 1:
            report.add(
                {
                    "type": TYPE_ZIP_NAME_COLLISION,
                    "kind": _file_kind(normalize_suffix(Path(key).suffix)),
                    "paths": names,
                    "message": f"zip 内同名条目将被覆盖: {key}",
                }
            )

    # Also detect case-insensitive collisions (Windows extract risk)
    lower_map: dict[str, list[str]] = defaultdict(list)
    for key in seen:
        lower_map[key.lower()].append(key)
    for _lk, keys in lower_map.items():
        uniq = sorted(set(keys))
        if len(uniq) > 1:
            report.add(
                {
                    "type": TYPE_ZIP_NAME_COLLISION,
                    "kind": _file_kind(normalize_suffix(Path(uniq[0]).suffix)),
                    "paths": uniq,
                    "message": f"zip 内大小写冲突路径（解压可能互相覆盖）: {', '.join(uniq)}",
                }
            )
    return report


def scan_extracted_duplicates(work_dir: Path, pair_dirs: list[Path]) -> DuplicateReport:
    """
    After extract: content-hash duplicates, left/right same bmp, cross-pair shared bmp.
    """
    report = DuplicateReport()
    work_dir = work_dir.resolve()
    pair_dir_set = {p.resolve() for p in pair_dirs}

    # hash -> [{rel, kind, pair_name}]
    by_hash: dict[str, list[dict]] = defaultdict(list)
    # pair_name -> list of bmp hashes in that pair
    pair_bmp_hashes: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for path in sorted(work_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel = str(path.resolve().relative_to(work_dir)).replace("\\", "/")
        except ValueError:
            continue
        suffix = normalize_suffix(path.suffix)
        kind = _file_kind(suffix)
        if kind == KIND_OTHER:
            continue
        try:
            digest = compute_hash(path.read_bytes())
        except OSError:
            continue

        parent = path.parent.resolve()
        pair_name = ""
        # Walk up to find owning pair dir
        cur = parent
        while True:
            if cur in pair_dir_set:
                pair_name = cur.name
                break
            if cur == work_dir or cur.parent == cur:
                break
            cur = cur.parent

        entry = {"path": rel, "kind": kind, "pair": pair_name, "name": path.name}
        by_hash[digest].append(entry)

        if kind == KIND_BMP and pair_name:
            pair_bmp_hashes[pair_name].append((digest, rel))

    # Content duplicates (same hash, multiple paths)
    for digest, entries in sorted(by_hash.items(), key=lambda x: x[0]):
        if len(entries) < 2:
            continue
        kinds = {e["kind"] for e in entries}
        kind = KIND_BMP if KIND_BMP in kinds else next(iter(kinds))
        paths = [e["path"] for e in entries]
        report.add(
            {
                "type": TYPE_ZIP_DUPLICATE_CONTENT,
                "kind": kind,
                "hash": digest[:16],
                "paths": paths,
                "message": f"包内相同内容出现 {len(paths)} 次（{kind}）",
            }
        )

    # Left/right same bmp within a pair
    for pair_name, items in sorted(pair_bmp_hashes.items()):
        if len(items) < 2:
            continue
        hashes = [h for h, _ in items]
        if len(set(hashes)) == 1 and len(hashes) >= 2:
            report.add(
                {
                    "type": TYPE_PAIR_SAME_BMP,
                    "kind": KIND_BMP,
                    "hash": hashes[0][:16],
                    "pair": pair_name,
                    "paths": [p for _, p in items],
                    "message": f"配对 {pair_name} 左右两侧 bmp 内容相同",
                }
            )

    # Cross-pair shared bmp (same hash used by >=2 different pair dirs)
    bmp_hash_pairs: dict[str, set[str]] = defaultdict(set)
    bmp_hash_paths: dict[str, list[str]] = defaultdict(list)
    for digest, entries in by_hash.items():
        for e in entries:
            if e["kind"] != KIND_BMP or not e["pair"]:
                continue
            bmp_hash_pairs[digest].add(e["pair"])
            bmp_hash_paths[digest].append(e["path"])
    for digest, pairs in sorted(bmp_hash_pairs.items(), key=lambda x: x[0]):
        if len(pairs) < 2:
            continue
        # Avoid double-counting pure pair_same_bmp (single pair with two identical files)
        # only flag when multiple pair directories share the content
        report.add(
            {
                "type": TYPE_CROSS_PAIR_SHARED_BMP,
                "kind": KIND_BMP,
                "hash": digest[:16],
                "pairs": sorted(pairs),
                "paths": bmp_hash_paths[digest],
                "message": f"多个配对目录共用同一 bmp 内容: {', '.join(sorted(pairs))}",
            }
        )

    return report


def merge_reports(*reports: DuplicateReport) -> DuplicateReport:
    merged = DuplicateReport()
    for report in reports:
        for warning in report.warnings:
            merged.add(warning)
    return merged


def detect_pair_same_bmp(pair_dir: Path) -> dict | None:
    """Return a warning dict if the two bmps in a pair dir share content."""
    if not pair_dir.is_dir():
        return None
    bmps = sorted(
        p for p in pair_dir.iterdir() if p.is_file() and normalize_suffix(p.suffix) == "bmp"
    )
    if len(bmps) != 2:
        return None
    h0 = compute_hash(bmps[0].read_bytes())
    h1 = compute_hash(bmps[1].read_bytes())
    if h0 != h1:
        return None
    return {
        "type": TYPE_PAIR_SAME_BMP,
        "kind": KIND_BMP,
        "hash": h0[:16],
        "pair": pair_dir.name,
        "paths": [bmp.name for bmp in bmps],
        "message": f"配对 {pair_dir.name} 左右两侧 bmp 内容相同",
    }
