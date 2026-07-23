"""Browse fingerprint images/features from business tables (T_CAP_FP_DATA + T_FEATURE_RECORD).

UI consumes a panels[] payload so a future pair mode can add a second panel without
changing decode/storage logic.
"""
from __future__ import annotations

import logging
from typing import Any

from django.db import close_old_connections, connections

from fingerprints.iso_decode import IsoDecodeError, iso_feature_to_minutiae
from fingerprints.layer_config import get_layer_type, list_layer_types, seed_default_layer_types
from fingerprints.path_writeback import (
    CAP_TABLE,
    DEFAULT_DATABASE,
    FEATURE_TABLE,
    normalize_relative_path,
)
from images.external_db_service import ExternalDbError, db_alias_session, external_alias
from utils.storage import get_image_storage

logger = logging.getLogger(__name__)

# Business feature columns → fingerprint_layer_type.layer_key
FEATURE_COLUMN_MAP: tuple[tuple[str, str], ...] = (
    ("feature_ara_data", "bidiso"),
    ("feature_neuro_data", "neuiso"),
)


class BizBrowseError(Exception):
    """Invalid config or missing business row."""


def parse_biz_connection_params(
    *,
    connection_id: Any = None,
    db_alias: str | None = None,
    database: str | None = None,
) -> dict:
    """
    Normalize browse connection params (same shape as path writeback).

      {
        "connection_id": 3 | None,
        "db_alias": "default",
        "database": "ara_fp_analyst" | ""
      }
    """
    cfg: dict[str, Any] = {}
    if connection_id is not None and str(connection_id).strip() != "":
        try:
            cfg["connection_id"] = int(connection_id)
        except (TypeError, ValueError) as exc:
            raise BizBrowseError("connection_id 无效") from exc
        cfg["database"] = (database if database is not None else DEFAULT_DATABASE) or DEFAULT_DATABASE
    else:
        cfg["db_alias"] = (db_alias or "default").strip() or "default"
        # Empty database keeps the alias default NAME (used by unit tests on sqlite).
        cfg["database"] = (database if database is not None else "") or ""
    return cfg


def _resolve_alias(config: dict) -> str:
    if config.get("connection_id") is not None:
        return external_alias(int(config["connection_id"]))
    return str(config.get("db_alias") or "default")


def decode_path_cell(value: Any) -> str:
    """Decode path stored as utf8 bytes in BLOB/varchar."""
    if value is None:
        return ""
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8", errors="replace")
    return normalize_relative_path(str(value).strip())


def _with_biz_cursor(config: dict):
    alias = _resolve_alias(config)
    database = str(config.get("database") or "").strip() or None
    close_old_connections()
    return db_alias_session(alias, database=database)


def list_biz_samples(
    config: dict,
    *,
    dataset_code: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> dict:
    """Paginated rows from T_CAP_FP_DATA."""
    page = max(1, int(page or 1))
    page_size = min(max(1, int(page_size or 100)), 500)
    offset = (page - 1) * page_size

    where = ["1=1"]
    params: list[Any] = []
    ds = (dataset_code or "").strip()
    if ds:
        where.append("`dataset_code`=%s")
        params.append(ds[:32])
    kw = (keyword or "").strip()
    if kw:
        where.append("(`cap_image_id` LIKE %s)")
        params.append(f"%{kw}%")

    where_sql = " AND ".join(where)
    count_sql = f"SELECT COUNT(*) FROM `{CAP_TABLE}` WHERE {where_sql}"
    list_sql = (
        f"SELECT `cap_image_id`, `dataset_code` FROM `{CAP_TABLE}` "
        f"WHERE {where_sql} ORDER BY `dataset_code`, `cap_image_id` "
        f"LIMIT %s OFFSET %s"
    )

    try:
        with _with_biz_cursor(config) as session_alias:
            conn = connections[session_alias]
            with conn.cursor() as cursor:
                cursor.execute(count_sql, params)
                total = int(cursor.fetchone()[0] or 0)
                cursor.execute(list_sql, [*params, page_size, offset])
                rows = cursor.fetchall()
    except ExternalDbError as exc:
        raise BizBrowseError(str(exc)) from exc
    except Exception as exc:
        logger.exception("list_biz_samples failed")
        raise BizBrowseError(f"读取 {CAP_TABLE} 失败: {exc}") from exc

    items = [
        {
            "cap_image_id": str(r[0] or ""),
            "dataset_code": str(r[1] or ""),
        }
        for r in rows
    ]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


def list_biz_meta(config: dict) -> dict:
    """Distinct dataset_code values + enabled layer types."""
    seed_default_layer_types()
    dataset_codes: list[str] = []
    try:
        with _with_biz_cursor(config) as session_alias:
            conn = connections[session_alias]
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT DISTINCT `dataset_code` FROM `{CAP_TABLE}` "
                    f"WHERE `dataset_code` IS NOT NULL AND `dataset_code`<>'' "
                    f"ORDER BY `dataset_code`"
                )
                dataset_codes = [str(r[0]) for r in cursor.fetchall() if r and r[0]]
    except ExternalDbError as exc:
        raise BizBrowseError(str(exc)) from exc
    except Exception as exc:
        logger.exception("list_biz_meta failed")
        raise BizBrowseError(f"读取 {CAP_TABLE} 元数据失败: {exc}") from exc

    return {
        "dataset_codes": dataset_codes,
        "layer_types": [info.to_dict() for info in list_layer_types(enabled_only=True)],
        "cap_table": CAP_TABLE,
        "feature_table": FEATURE_TABLE,
        "database": str(config.get("database") or "") or DEFAULT_DATABASE,
    }


def _load_layer_from_template(
    *,
    layer_type: str,
    template_path: str,
    selected_layer_types: set[str] | None,
) -> dict | None:
    if not template_path:
        return None
    if selected_layer_types is not None and layer_type not in selected_layer_types:
        return None

    meta = get_layer_type(layer_type)
    color = meta.color if meta else "#888888"
    label = meta.label if meta else layer_type
    setlen = meta.default_setlen if meta else 0
    setang = meta.default_setang if meta else 256

    layer: dict[str, Any] = {
        "side": "primary",
        "layer_type": layer_type,
        "label": label,
        "color": color,
        "algo_name": meta.default_algo_name if meta else layer_type,
        "algo_version": "biz",
        "template_path": template_path,
        "file_suffix": template_path.rsplit(".", 1)[-1] if "." in template_path else "",
        "minutiae_count": 0,
        "minutiae": {"count": 0, "setlen": setlen, "setang": setang, "minutiae": []},
        "error": None,
    }
    try:
        content = get_image_storage().read_bytes(template_path)
        result = iso_feature_to_minutiae(content, setlen=setlen, setang=setang)
        layer["minutiae"] = result.to_dict()
        layer["minutiae_count"] = result.count
    except FileNotFoundError:
        layer["error"] = f"特征文件不存在: {template_path}"
    except IsoDecodeError as exc:
        layer["error"] = f"ISO 解码失败: {exc}"
    except Exception as exc:
        logger.warning("template load failed path=%s err=%s", template_path, exc)
        layer["error"] = f"读取特征失败: {exc}"
    return layer


def build_sample_view(
    config: dict,
    cap_image_id: str,
    *,
    selected_layer_types: list[str] | None = None,
    show_labels: bool = True,
) -> dict:
    """
    Single-sample view payload:

      { mode, panels: [{ role, cap_image_id, dataset_code, image, layers }], pair_meta }
    """
    cap_image_id = str(cap_image_id or "").strip()
    if not cap_image_id:
        raise BizBrowseError("cap_image_id 不能为空")

    selected: set[str] | None = None
    if selected_layer_types is not None:
        selected = {x.strip().lower() for x in selected_layer_types if x and str(x).strip()}

    try:
        with _with_biz_cursor(config) as session_alias:
            conn = connections[session_alias]
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT `cap_image_id`, `dataset_code`, `fingerprint_image`
                    FROM `{CAP_TABLE}`
                    WHERE `cap_image_id`=%s
                    LIMIT 1
                    """,
                    [cap_image_id],
                )
                cap_row = cursor.fetchone()
                if not cap_row:
                    raise BizBrowseError(f"未找到捕获记录: {cap_image_id}")

                cursor.execute(
                    f"""
                    SELECT `feature_ara_data`, `feature_neuro_data`
                    FROM `{FEATURE_TABLE}`
                    WHERE `fp_image_id`=%s
                    LIMIT 1
                    """,
                    [cap_image_id],
                )
                feat_row = cursor.fetchone()
    except BizBrowseError:
        raise
    except ExternalDbError as exc:
        raise BizBrowseError(str(exc)) from exc
    except Exception as exc:
        logger.exception("build_sample_view query failed id=%s", cap_image_id)
        raise BizBrowseError(f"读取业务表失败: {exc}") from exc

    image_path = decode_path_cell(cap_row[2])
    if not image_path:
        raise BizBrowseError(f"{cap_image_id}: fingerprint_image 路径为空")

    image_error = None
    try:
        # Ensure object exists; bytes are served via /images/file/?path=
        get_image_storage().read_bytes(image_path)
    except Exception as exc:
        image_error = f"图像文件不可读: {exc}"

    layers: list[dict] = []
    if feat_row:
        col_values = {
            "feature_ara_data": decode_path_cell(feat_row[0]),
            "feature_neuro_data": decode_path_cell(feat_row[1]),
        }
        for col_name, layer_key in FEATURE_COLUMN_MAP:
            path = col_values.get(col_name) or ""
            layer = _load_layer_from_template(
                layer_type=layer_key,
                template_path=path,
                selected_layer_types=selected,
            )
            if layer:
                layer["show_labels"] = show_labels
                layers.append(layer)

    available_types = sorted({layer["layer_type"] for layer in layers})
    panel = {
        "role": "primary",
        "cap_image_id": str(cap_row[0] or ""),
        "dataset_code": str(cap_row[1] or ""),
        "image": {
            "path": image_path,
            "url": "",  # client loads via authenticated /images/file/?path=
            "error": image_error,
        },
        "layers": layers,
        "available_layer_types": available_types,
    }

    return {
        "mode": "single",
        "panels": [panel],
        "pair_meta": None,
        "available_layer_types": available_types,
        "layer_type_options": [info.to_dict() for info in list_layer_types(enabled_only=True)],
    }
