"""Fingerprint pair import, listing, and overlay payload services."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.db import close_old_connections, connection
from django.db.models import Q

from fingerprints.iso_decode import (
    DEFAULT_SETANG,
    DEFAULT_SETLEN,
    IsoDecodeError,
    iso_feature_to_minutiae,
)
from fingerprints.layer_config import (
    LayerTypeInfo,
    allowed_template_suffixes,
    get_layer_type,
    list_layer_types,
    resolve_layer_type_by_suffix,
    version_color,
)
from fingerprints.models import FingerprintFeatureLayer, FingerprintPair
from images.models import ImageInfo
from images.services import DuplicateImageError, save_image_bytes
from utils.db_time import fetch_db_now
from utils.file_security import UploadValidationError, validate_template_file
from utils.path_builder import build_template_relative_path, normalize_suffix
from utils.storage import get_image_storage

logger = logging.getLogger(__name__)

PAIR_DIR_RE = re.compile(r"^(?P<id>\d+)-(?P<score>[0-9.]+)(?:_(?P<dup>\d+))?$")
SAMPLE_NAME_RE = re.compile(
    r"^(?P<person>\d+)_(?P<hand>left|right)_(?P<finger>thumb|index|middle|ring|little)$",
    re.IGNORECASE,
)


class FingerprintImportError(Exception):
    """Raised when a batmatch-style pair cannot be imported."""


@dataclass
class PairImportResult:
    pair_id: int
    batch_name: str
    finger_position: str
    layer_count: int
    skipped: bool = False
    message: str = ""
    layers_added: int = 0
    pair_created: bool = False


def compute_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def parse_pair_dirname(name: str) -> tuple[str, float | None]:
    match = PAIR_DIR_RE.match(name)
    if not match:
        return name, None
    try:
        return name, float(match.group("score"))
    except ValueError:
        return name, None


def parse_sample_stem(stem: str) -> tuple[str, str]:
    """Return (person_id, finger_position) from filename stem."""
    match = SAMPLE_NAME_RE.match(stem)
    if not match:
        raise FingerprintImportError(f"无法解析文件名: {stem}")
    position = f"{match.group('hand').lower()}_{match.group('finger').lower()}"
    return match.group("person"), position


def _group_pair_files(pair_dir: Path) -> dict[str, dict[str, Path]]:
    """
    Group files in a pair folder by sample stem.

    Returns: {stem: {"bmp": Path, "bidiso": Path, "neuiso": Path, ...}}
    """
    groups: dict[str, dict[str, Path]] = {}
    for path in sorted(pair_dir.iterdir()):
        if not path.is_file():
            continue
        stem = path.stem
        suffix = normalize_suffix(path.suffix)
        groups.setdefault(stem, {})[suffix] = path
    return groups


def _save_template(
    *,
    filename: str,
    content: bytes,
    layer_info: LayerTypeInfo,
    algo_version: str,
) -> tuple[str, str, int]:
    validated = validate_template_file(
        filename,
        content,
        allowed_suffixes=allowed_template_suffixes(),
        max_bytes=getattr(settings, "MAX_UPLOAD_SIZE_BYTES", 20 * 1024 * 1024),
    )
    relative_path = build_template_relative_path(validated.suffix)
    get_image_storage().write_bytes(relative_path, content)
    return relative_path, validated.suffix, validated.size


def _decode_and_cache(content: bytes, *, setlen: int, setang: int) -> tuple[int, str]:
    result = iso_feature_to_minutiae(content, setlen=setlen, setang=setang)
    return result.count, json.dumps(result.to_dict(), ensure_ascii=False, separators=(",", ":"))


def import_pair_directory(
    pair_dir: Path,
    *,
    upload_user: str,
    tags: str = "",
    algo_version: str = "1.0",
    category_id: int | None = None,
    skip_existing: bool = True,
) -> PairImportResult:
    """
    Import one batmatch_out-style pair folder.

    Pair identity: batch_name + finger_position + left/right person_id.
    Layer identity: pair + side + layer_type + algo_name + algo_version.

    Re-importing the same zip with a *new* algo_version merges new feature layers
    onto the existing pair (version compare). Same version layers are skipped when
    skip_existing=True.
    """
    if not pair_dir.is_dir():
        raise FingerprintImportError(f"不是目录: {pair_dir}")

    algo_version = (algo_version or "1.0").strip() or "1.0"
    batch_name, match_score = parse_pair_dirname(pair_dir.name)
    groups = _group_pair_files(pair_dir)
    bmp_stems = [stem for stem, files in groups.items() if "bmp" in files]
    if len(bmp_stems) != 2:
        raise FingerprintImportError(
            f"{pair_dir.name}: 需要恰好 2 张 bmp，实际 {len(bmp_stems)}"
        )

    samples: list[tuple[str, str, dict[str, Path]]] = []
    positions: set[str] = set()
    for stem in sorted(bmp_stems):
        person_id, position = parse_sample_stem(stem)
        positions.add(position)
        samples.append((person_id, stem, groups[stem]))
    if len(positions) != 1:
        raise FingerprintImportError(f"{pair_dir.name}: 两侧指位不一致: {positions}")
    finger_position = next(iter(positions))

    now = fetch_db_now()
    pair = FingerprintPair.objects.filter(
        is_delete=0,
        batch_name=batch_name,
        finger_position=finger_position,
        left_person_id=samples[0][0],
        right_person_id=samples[1][0],
    ).first()
    pair_created = False

    if pair is None:
        def _save_one_bmp(item: tuple[str, str, dict[str, Path]]) -> tuple[str, ImageInfo]:
            person_id, _stem, files = item
            close_old_connections()
            bmp_path = files["bmp"]
            content = bmp_path.read_bytes()
            try:
                image = save_image_bytes(
                    filename=bmp_path.name,
                    content=content,
                    upload_user=upload_user,
                    category_id=category_id,
                    tags=tags or "fingerprint",
                )
            except DuplicateImageError as exc:
                image = exc.existing
            finally:
                close_old_connections()
            return person_id, image

        from django.db import connection as db_connection

        if db_connection.vendor == "sqlite":
            bmp_results = [_save_one_bmp(item) for item in samples]
        else:
            with ThreadPoolExecutor(max_workers=2) as pool:
                bmp_results = list(pool.map(_save_one_bmp, samples))

        image_ids = [img.id for _pid, img in bmp_results]
        image_names = [img.image_name for _pid, img in bmp_results]
        person_ids = [pid for pid, _img in bmp_results]

        pair = FingerprintPair.objects.create(
            batch_name=batch_name,
            finger_position=finger_position,
            match_score=match_score,
            left_image_id=image_ids[0],
            right_image_id=image_ids[1],
            left_person_id=person_ids[0],
            right_person_id=person_ids[1],
            left_image_name=image_names[0],
            right_image_name=image_names[1],
            source_dir=str(pair_dir.name),
            upload_user=upload_user,
            tags=(tags or "").strip()[:500],
            is_delete=0,
            create_time=now,
            update_time=now,
        )
        pair_created = True
    elif match_score is not None and pair.match_score != match_score:
        pair.match_score = match_score
        pair.update_time = now
        pair.save(update_fields=["match_score", "update_time"])

    template_jobs: list[tuple[str, Path, LayerTypeInfo]] = []
    unknown_suffixes: list[str] = []
    sides = ("left", "right")
    for side, (_person, _stem, files) in zip(sides, samples):
        for suffix, path in files.items():
            if suffix == "bmp":
                continue
            layer_info = resolve_layer_type_by_suffix(suffix)
            if layer_info is None:
                unknown_suffixes.append(suffix)
                logger.warning("skip unknown template suffix=%s file=%s", suffix, path.name)
                continue
            if skip_existing and FingerprintFeatureLayer.objects.filter(
                pair_id=pair.id,
                side=side,
                layer_type=layer_info.layer_key,
                algo_name=layer_info.default_algo_name,
                algo_version=algo_version,
            ).exists():
                continue
            template_jobs.append((side, path, layer_info))

    def _save_one_template(job: tuple[str, Path, LayerTypeInfo]) -> dict:
        side, path, layer_info = job
        close_old_connections()
        content = path.read_bytes()
        try:
            template_path, file_suffix, file_size = _save_template(
                filename=path.name,
                content=content,
                layer_info=layer_info,
                algo_version=algo_version,
            )
            count, cache = _decode_and_cache(
                content,
                setlen=layer_info.default_setlen,
                setang=layer_info.default_setang,
            )
        except (UploadValidationError, IsoDecodeError) as exc:
            raise FingerprintImportError(f"{path.name}: {exc}") from exc
        finally:
            close_old_connections()
        return {
            "side": side,
            "layer_info": layer_info,
            "template_path": template_path,
            "file_suffix": file_suffix,
            "file_size": file_size,
            "content_hash": compute_hash(content),
            "count": count,
            "cache": cache,
        }

    layer_rows: list[dict] = []
    if template_jobs:
        if connection.vendor == "sqlite":
            layer_rows = [_save_one_template(job) for job in template_jobs]
        else:
            with ThreadPoolExecutor(max_workers=min(4, len(template_jobs))) as pool:
                futures = [pool.submit(_save_one_template, job) for job in template_jobs]
                for fut in as_completed(futures):
                    layer_rows.append(fut.result())

    for row in layer_rows:
        info: LayerTypeInfo = row["layer_info"]
        FingerprintFeatureLayer.objects.create(
            pair_id=pair.id,
            side=row["side"],
            layer_type=info.layer_key,
            algo_name=info.default_algo_name,
            algo_version=algo_version,
            template_path=row["template_path"],
            file_suffix=row["file_suffix"],
            file_hash=row["content_hash"],
            file_size=row["file_size"],
            setlen=info.default_setlen,
            setang=info.default_setang,
            minutiae_count=row["count"],
            minutiae_json=row["cache"],
            create_time=now,
        )

    total_layers = FingerprintFeatureLayer.objects.filter(pair_id=pair.id).count()
    layers_added = len(layer_rows)
    if layers_added == 0 and not pair_created:
        msg = f"already has version {algo_version}"
        if unknown_suffixes:
            msg += f"; unknown suffixes: {', '.join(sorted(set(unknown_suffixes)))}"
        return PairImportResult(
            pair_id=pair.id,
            batch_name=batch_name,
            finger_position=finger_position,
            layer_count=total_layers,
            skipped=True,
            message=msg,
            layers_added=0,
            pair_created=False,
        )

    msg = "created pair" if pair_created else f"merged version {algo_version}"
    if unknown_suffixes:
        msg += f"; skipped unknown suffixes: {', '.join(sorted(set(unknown_suffixes)))}"
    return PairImportResult(
        pair_id=pair.id,
        batch_name=batch_name,
        finger_position=finger_position,
        layer_count=total_layers,
        skipped=False,
        message=msg,
        layers_added=layers_added,
        pair_created=pair_created,
    )


def _dir_looks_like_pair(path: Path) -> bool:
    """True when directory has exactly two fingerprint bmps (same finger position)."""
    if not path.is_dir():
        return False
    bmps = [p for p in path.iterdir() if p.is_file() and normalize_suffix(p.suffix) == "bmp"]
    if len(bmps) != 2:
        return False
    positions: set[str] = set()
    for bmp in bmps:
        try:
            _person, position = parse_sample_stem(bmp.stem)
        except FingerprintImportError:
            return False
        positions.add(position)
    return len(positions) == 1


def discover_pair_dirs(root: Path) -> list[Path]:
    """
    Find batmatch pair directories under root.

    Accepts:
    - directories named like 101-1.111219
    - any directory containing exactly two fingerprint-named bmps
    Walks nested wrappers such as batmatch_out/batmatch_out/...
    """
    if not root.exists():
        return []

    found: list[Path] = []
    seen: set[str] = set()
    for dirpath, _dirnames, _filenames in os.walk(root):
        path = Path(dirpath)
        if not (_dir_looks_like_pair(path) or (PAIR_DIR_RE.match(path.name) and _dir_looks_like_pair(path))):
            # still accept PAIR_DIR_RE even if bmp count temporarily odd? prefer strict
            if not _dir_looks_like_pair(path):
                continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        found.append(path)
    return sorted(found, key=lambda p: p.name)


def import_from_zip(
    zip_bytes: bytes,
    *,
    upload_user: str,
    tags: str = "",
    algo_version: str = "1.0",
    category_id: int | None = None,
    skip_existing: bool = True,
) -> list[PairImportResult]:
    """Synchronous import (tests / small zips). Prefer background job for full packages."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="fp_import_") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            zf.extractall(tmp_path)
        pair_dirs = discover_pair_dirs(tmp_path)
        if not pair_dirs:
            raise FingerprintImportError("压缩包中未找到 batmatch 风格的成对目录")
        results: list[PairImportResult] = []
        for pair_dir in pair_dirs:
            results.append(
                import_pair_directory(
                    pair_dir,
                    upload_user=upload_user,
                    tags=tags,
                    algo_version=algo_version,
                    category_id=category_id,
                    skip_existing=skip_existing,
                )
            )
        return results


def import_from_uploaded_files(
    files: list[tuple[str, bytes]],
    *,
    upload_user: str,
    batch_name: str = "",
    match_score: float | None = None,
    tags: str = "",
    algo_version: str = "1.0",
    category_id: int | None = None,
) -> PairImportResult:
    """
    Import a single pair from multipart files.

    Each file name should be like personId_left_index.bmp / .Bidiso / .neuiso
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="fp_pair_") as tmp:
        pair_dir = Path(tmp) / (batch_name or "manual-0")
        pair_dir.mkdir(parents=True)
        for name, content in files:
            target = pair_dir / Path(name).name
            target.write_bytes(content)
        if batch_name and match_score is not None:
            # rename dir to batmatch style for score parsing
            named = pair_dir.parent / f"0-{match_score}"
            if named != pair_dir:
                pair_dir.rename(named)
                pair_dir = named
        elif batch_name:
            named = pair_dir.parent / batch_name
            if named != pair_dir:
                pair_dir.rename(named)
                pair_dir = named
        return import_pair_directory(
            pair_dir,
            upload_user=upload_user,
            tags=tags,
            algo_version=algo_version,
            category_id=category_id,
            skip_existing=False,
        )


def serialize_pair(pair: FingerprintPair, *, include_layers: bool = False) -> dict:
    qs = list(FingerprintFeatureLayer.objects.filter(pair_id=pair.id))
    layer_types = sorted({row.layer_type for row in qs})
    versions = sorted({row.algo_version for row in qs})
    data = {
        "id": pair.id,
        "batch_name": pair.batch_name,
        "finger_position": pair.finger_position,
        "match_score": pair.match_score,
        "left_image_id": pair.left_image_id,
        "right_image_id": pair.right_image_id,
        "left_person_id": pair.left_person_id,
        "right_person_id": pair.right_person_id,
        "left_image_name": pair.left_image_name,
        "right_image_name": pair.right_image_name,
        "source_dir": pair.source_dir,
        "upload_user": pair.upload_user,
        "tags": pair.tags,
        "create_time": pair.create_time.isoformat(sep=" ") if pair.create_time else None,
        "update_time": pair.update_time.isoformat(sep=" ") if pair.update_time else None,
        "layer_types": layer_types,
        "algo_versions": versions,
        "layer_count": len(qs),
    }
    if include_layers:
        data["layers"] = [serialize_layer(row, include_minutiae=False) for row in qs]
    return data


def serialize_layer(
    layer: FingerprintFeatureLayer,
    *,
    include_minutiae: bool = False,
    color: str | None = None,
) -> dict:
    data = {
        "id": layer.id,
        "pair_id": layer.pair_id,
        "side": layer.side,
        "layer_type": layer.layer_type,
        "algo_name": layer.algo_name,
        "algo_version": layer.algo_version,
        "template_path": layer.template_path,
        "file_suffix": layer.file_suffix,
        "file_size": layer.file_size,
        "setlen": layer.setlen,
        "setang": layer.setang,
        "minutiae_count": layer.minutiae_count,
        "color": color,
    }
    if include_minutiae:
        data["minutiae"] = load_layer_minutiae(layer)
    return data


def load_layer_minutiae(layer: FingerprintFeatureLayer) -> dict:
    if layer.minutiae_json:
        try:
            return json.loads(layer.minutiae_json)
        except json.JSONDecodeError:
            pass

    content = get_image_storage().read_bytes(layer.template_path)
    setlen = layer.setlen if layer.setlen is not None else DEFAULT_SETLEN
    setang = layer.setang if layer.setang is not None else DEFAULT_SETANG
    result = iso_feature_to_minutiae(content, setlen=setlen, setang=setang)
    cache = json.dumps(result.to_dict(), ensure_ascii=False, separators=(",", ":"))
    FingerprintFeatureLayer.objects.filter(id=layer.id).update(
        minutiae_json=cache,
        minutiae_count=result.count,
    )
    return result.to_dict()


def list_pairs(
    *,
    finger_position: str | None = None,
    batch_name: str | None = None,
    score_min: float | None = None,
    score_max: float | None = None,
    layer_type: str | None = None,
    algo_version: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    qs = FingerprintPair.objects.filter(is_delete=0)
    if finger_position:
        qs = qs.filter(finger_position=finger_position)
    if batch_name:
        qs = qs.filter(batch_name__icontains=batch_name)
    if score_min is not None:
        qs = qs.filter(match_score__gte=score_min)
    if score_max is not None:
        qs = qs.filter(match_score__lte=score_max)
    if keyword:
        qs = qs.filter(
            Q(left_image_name__icontains=keyword)
            | Q(right_image_name__icontains=keyword)
            | Q(left_person_id__icontains=keyword)
            | Q(right_person_id__icontains=keyword)
            | Q(batch_name__icontains=keyword)
            | Q(tags__icontains=keyword)
        )

    if layer_type or algo_version:
        layer_qs = FingerprintFeatureLayer.objects.all()
        if layer_type:
            layer_qs = layer_qs.filter(layer_type=layer_type)
        if algo_version:
            layer_qs = layer_qs.filter(algo_version=algo_version)
        pair_ids = layer_qs.values_list("pair_id", flat=True).distinct()
        qs = qs.filter(id__in=pair_ids)

    total = qs.count()
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    offset = (page - 1) * page_size
    rows = list(qs.order_by("-id")[offset : offset + page_size])
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [serialize_pair(row) for row in rows],
    }


def build_compare_payload(
    pair_id: int,
    *,
    selected_layer_types: list[str] | None = None,
    selected_versions: list[str] | None = None,
    show_labels: bool = True,
) -> dict:
    pair = FingerprintPair.objects.filter(id=pair_id, is_delete=0).first()
    if not pair:
        raise FingerprintImportError("配对不存在")

    left_image = ImageInfo.objects.filter(id=pair.left_image_id, is_delete=0).first()
    right_image = ImageInfo.objects.filter(id=pair.right_image_id, is_delete=0).first()
    if not left_image or not right_image:
        raise FingerprintImportError("配对关联图片缺失")

    layers = list(FingerprintFeatureLayer.objects.filter(pair_id=pair.id))
    type_meta = {info.layer_key: info for info in list_layer_types(enabled_only=False)}

    if selected_layer_types is not None:
        selected = {x.strip().lower() for x in selected_layer_types if x.strip()}
        layers = [layer for layer in layers if layer.layer_type.lower() in selected]
    if selected_versions is not None:
        versions = {x.strip() for x in selected_versions if x.strip()}
        layers = [layer for layer in layers if layer.algo_version in versions]

    # version colors per layer_type
    versions_by_type: dict[str, list[str]] = {}
    for layer in layers:
        versions_by_type.setdefault(layer.layer_type, [])
        if layer.algo_version not in versions_by_type[layer.layer_type]:
            versions_by_type[layer.layer_type].append(layer.algo_version)
    for key in versions_by_type:
        versions_by_type[key] = sorted(versions_by_type[key])

    overlay_layers = []
    for layer in layers:
        meta = type_meta.get(layer.layer_type) or get_layer_type(layer.layer_type)
        base_color = meta.color if meta else "#888888"
        color = version_color(
            base_color,
            layer.algo_version,
            versions_by_type.get(layer.layer_type, [layer.algo_version]),
        )
        payload = serialize_layer(layer, include_minutiae=True, color=color)
        payload["label"] = meta.label if meta else layer.layer_type
        payload["show_labels"] = show_labels
        overlay_layers.append(payload)

    available_types = sorted({layer.layer_type for layer in FingerprintFeatureLayer.objects.filter(pair_id=pair.id)})
    available_versions = sorted(
        {layer.algo_version for layer in FingerprintFeatureLayer.objects.filter(pair_id=pair.id)}
    )

    return {
        "pair": serialize_pair(pair, include_layers=False),
        "left": {
            "side": "left",
            "image_id": left_image.id,
            "image_name": left_image.image_name,
            "image_path": left_image.image_path,
            "width": left_image.image_width,
            "height": left_image.image_height,
            "person_id": pair.left_person_id,
        },
        "right": {
            "side": "right",
            "image_id": right_image.id,
            "image_name": right_image.image_name,
            "image_path": right_image.image_path,
            "width": right_image.image_width,
            "height": right_image.image_height,
            "person_id": pair.right_person_id,
        },
        "layers": overlay_layers,
        "available_layer_types": available_types,
        "available_algo_versions": available_versions,
        "layer_type_options": [info.to_dict() for info in list_layer_types(enabled_only=True)],
    }
