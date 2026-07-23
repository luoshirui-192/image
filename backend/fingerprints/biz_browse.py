"""Browse fingerprint pairs from business tables.

Pair list: t_match_result_image (image_reg / image_match = T_CAP_FP_DATA.cap_image_id stems)
Per side: T_CAP_FP_DATA + T_FEATURE_RECORD → image path + minutiae layers

UI consumes panels[] (mode=pair → length 2). Metrics (score/sameflag/*ms) deferred.
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

MATCH_TABLE = "t_match_result_image"

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


def list_biz_pairs(
    config: dict,
    *,
    dataset_code: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> dict:
    """Paginated pairing rows from t_match_result_image (no metric fields)."""
    page = max(1, int(page or 1))
    page_size = min(max(1, int(page_size or 100)), 500)
    offset = (page - 1) * page_size

    where = ["1=1"]
    params: list[Any] = []
    ds = (dataset_code or "").strip()
    if ds:
        where.append("`data_set_code`=%s")
        params.append(ds)
    kw = (keyword or "").strip()
    if kw:
        where.append("(`image_reg` LIKE %s OR `image_match` LIKE %s OR CAST(`id` AS CHAR) LIKE %s)")
        like = f"%{kw}%"
        params.extend([like, like, like])

    where_sql = " AND ".join(where)
    count_sql = f"SELECT COUNT(*) FROM `{MATCH_TABLE}` WHERE {where_sql}"
    list_sql = (
        f"SELECT `id`, `image_reg`, `image_match`, `data_set_code` FROM `{MATCH_TABLE}` "
        f"WHERE {where_sql} ORDER BY `data_set_code`, `id` "
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
        logger.exception("list_biz_pairs failed")
        raise BizBrowseError(f"读取 {MATCH_TABLE} 失败: {exc}") from exc

    items = [
        {
            "id": int(r[0]),
            "image_reg": str(r[1] or "").strip(),
            "image_match": str(r[2] or "").strip(),
            "data_set_code": str(r[3] or "").strip(),
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
    """Distinct dataset codes from match + CAP tables + enabled layer types."""
    seed_default_layer_types()
    codes: set[str] = set()
    try:
        with _with_biz_cursor(config) as session_alias:
            conn = connections[session_alias]
            with conn.cursor() as cursor:
                try:
                    cursor.execute(
                        f"SELECT DISTINCT `data_set_code` FROM `{MATCH_TABLE}` "
                        f"WHERE `data_set_code` IS NOT NULL AND `data_set_code`<>''"
                    )
                    for r in cursor.fetchall():
                        if r and r[0]:
                            codes.add(str(r[0]))
                except Exception:
                    logger.warning("list_biz_meta: read %s codes failed", MATCH_TABLE, exc_info=True)
                try:
                    cursor.execute(
                        f"SELECT DISTINCT `dataset_code` FROM `{CAP_TABLE}` "
                        f"WHERE `dataset_code` IS NOT NULL AND `dataset_code`<>''"
                    )
                    for r in cursor.fetchall():
                        if r and r[0]:
                            codes.add(str(r[0]))
                except Exception:
                    logger.warning("list_biz_meta: read %s codes failed", CAP_TABLE, exc_info=True)
    except ExternalDbError as exc:
        raise BizBrowseError(str(exc)) from exc
    except Exception as exc:
        logger.exception("list_biz_meta failed")
        raise BizBrowseError(f"读取业务表元数据失败: {exc}") from exc

    return {
        "dataset_codes": sorted(codes),
        "layer_types": [info.to_dict() for info in list_layer_types(enabled_only=True)],
        "cap_table": CAP_TABLE,
        "feature_table": FEATURE_TABLE,
        "match_table": MATCH_TABLE,
        "database": str(config.get("database") or "") or DEFAULT_DATABASE,
    }


def _load_layer_from_template(
    *,
    layer_type: str,
    template_path: str,
    selected_layer_types: set[str] | None,
    side: str,
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
        "side": side,
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


def _fetch_cap_and_feature(cursor, cap_image_id: str) -> tuple[Any, Any]:
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
    feat_row = None
    if cap_row:
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
    return cap_row, feat_row


def build_panel_for_cap(
    config: dict,
    cap_image_id: str,
    *,
    role: str,
    selected_layer_types: set[str] | None = None,
    show_labels: bool = True,
    cursor=None,
) -> dict:
    """
    Build one panel from T_CAP_FP_DATA + T_FEATURE_RECORD.
    Missing cap/path yields panel.error instead of raising (pair view stays usable).
    """
    cap_image_id = str(cap_image_id or "").strip()
    empty = {
        "role": role,
        "cap_image_id": cap_image_id,
        "dataset_code": "",
        "image": {"path": "", "url": "", "error": None},
        "layers": [],
        "available_layer_types": [],
        "error": None,
    }
    if not cap_image_id:
        empty["error"] = "一侧 stem 为空"
        empty["image"]["error"] = empty["error"]
        return empty

    def _build(cur) -> dict:
        cap_row, feat_row = _fetch_cap_and_feature(cur, cap_image_id)
        if not cap_row:
            panel = dict(empty)
            panel["error"] = f"未找到捕获记录: {cap_image_id}"
            panel["image"]["error"] = panel["error"]
            return panel

        image_path = decode_path_cell(cap_row[2])
        image_error = None
        if not image_path:
            image_error = f"{cap_image_id}: fingerprint_image 路径为空"
        else:
            try:
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
                    selected_layer_types=selected_layer_types,
                    side=role,
                )
                if layer:
                    layer["show_labels"] = show_labels
                    layers.append(layer)

        available_types = sorted({layer["layer_type"] for layer in layers})
        return {
            "role": role,
            "cap_image_id": str(cap_row[0] or ""),
            "dataset_code": str(cap_row[1] or ""),
            "image": {
                "path": image_path,
                "url": "",
                "error": image_error,
            },
            "layers": layers,
            "available_layer_types": available_types,
            "error": image_error,
        }

    if cursor is not None:
        return _build(cursor)

    try:
        with _with_biz_cursor(config) as session_alias:
            conn = connections[session_alias]
            with conn.cursor() as cur:
                return _build(cur)
    except ExternalDbError as exc:
        raise BizBrowseError(str(exc)) from exc
    except BizBrowseError:
        raise
    except Exception as exc:
        logger.exception("build_panel_for_cap failed id=%s", cap_image_id)
        raise BizBrowseError(f"读取业务表失败: {exc}") from exc


def build_sample_view(
    config: dict,
    cap_image_id: str,
    *,
    selected_layer_types: list[str] | None = None,
    show_labels: bool = True,
) -> dict:
    """Single-sample view (compat). Raises if stem empty / hard config errors."""
    selected: set[str] | None = None
    if selected_layer_types is not None:
        selected = {x.strip().lower() for x in selected_layer_types if x and str(x).strip()}

    panel = build_panel_for_cap(
        config,
        cap_image_id,
        role="primary",
        selected_layer_types=selected,
        show_labels=show_labels,
    )
    if panel.get("error") and not panel.get("image", {}).get("path"):
        raise BizBrowseError(panel["error"] or "样本不可用")

    available_types = panel.get("available_layer_types") or []
    return {
        "mode": "single",
        "panels": [panel],
        "pair_meta": None,
        "available_layer_types": available_types,
        "layer_type_options": [info.to_dict() for info in list_layer_types(enabled_only=True)],
    }


def build_pair_view(
    config: dict,
    match_id: int | str,
    *,
    selected_layer_types: list[str] | None = None,
    show_labels: bool = True,
) -> dict:
    """
    Dual-panel view from t_match_result_image.

    pair_meta only carries identity fields (metrics deferred).
    """
    try:
        mid = int(match_id)
    except (TypeError, ValueError) as exc:
        raise BizBrowseError("配对 id 无效") from exc

    selected: set[str] | None = None
    if selected_layer_types is not None:
        selected = {x.strip().lower() for x in selected_layer_types if x and str(x).strip()}

    try:
        with _with_biz_cursor(config) as session_alias:
            conn = connections[session_alias]
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT `id`, `image_reg`, `image_match`, `data_set_code`
                    FROM `{MATCH_TABLE}`
                    WHERE `id`=%s
                    LIMIT 1
                    """,
                    [mid],
                )
                row = cursor.fetchone()
                if not row:
                    raise BizBrowseError(f"未找到配对记录: {mid}")

                image_reg = str(row[1] or "").strip()
                image_match = str(row[2] or "").strip()
                data_set_code = str(row[3] or "").strip()

                left = build_panel_for_cap(
                    config,
                    image_reg,
                    role="reg",
                    selected_layer_types=selected,
                    show_labels=show_labels,
                    cursor=cursor,
                )
                right = build_panel_for_cap(
                    config,
                    image_match,
                    role="match",
                    selected_layer_types=selected,
                    show_labels=show_labels,
                    cursor=cursor,
                )
    except BizBrowseError:
        raise
    except ExternalDbError as exc:
        raise BizBrowseError(str(exc)) from exc
    except Exception as exc:
        logger.exception("build_pair_view failed id=%s", mid)
        raise BizBrowseError(f"读取配对失败: {exc}") from exc

    available_types = sorted(
        set(left.get("available_layer_types") or []) | set(right.get("available_layer_types") or [])
    )
    return {
        "mode": "pair",
        "panels": [left, right],
        "pair_meta": {
            "id": mid,
            "image_reg": image_reg,
            "image_match": image_match,
            "data_set_code": data_set_code,
        },
        "available_layer_types": available_types,
        "layer_type_options": [info.to_dict() for info in list_layer_types(enabled_only=True)],
    }


# Backward-compatible alias used by older sample list UI
def list_biz_samples(
    config: dict,
    *,
    dataset_code: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> dict:
    """Deprecated path: list T_CAP_FP_DATA. Prefer list_biz_pairs."""
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
