"""Biometric eval metrics from t_match_result_image.

Unit: data_set_code.
Score columns (user mapping): score (default), NeuNTms, Bionems, BioIdms, HXms, AlgVersion.
sameflag: 1 = Genuine, 0 = Impostor.

Higher score = more similar (accept when score >= threshold).
"""
from __future__ import annotations

import logging
import math
import re
from bisect import bisect_left, bisect_right
from typing import Any

from django.db import close_old_connections, connections

from fingerprints.biz_browse import BizBrowseError, MATCH_TABLE, parse_biz_connection_params
from fingerprints.path_writeback import DEFAULT_DATABASE
from images.external_db_service import ExternalDbError, alias_from_connection_config, db_alias_session

logger = logging.getLogger(__name__)

# (column_name, display_label) — AlgVersion treated as score per product owner.
SCORE_COLUMN_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("score", "score（默认）"),
    ("NeuNTms", "NeuNTms"),
    ("Bionems", "Bionems"),
    ("BioIdms", "BioIdms"),
    ("HXms", "HXms"),
    ("AlgVersion", "AlgVersion"),
)

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MIN_PAIR_COUNT = 2  # at least some genuine + impostor rows to offer a column


class BizEvalError(BizBrowseError):
    """Invalid eval request or insufficient data."""


def _quote_ident(name: str) -> str:
    value = (name or "").strip()
    if not _IDENT_RE.match(value):
        raise BizEvalError(f"非法列名: {name}")
    return f"`{value}`"


def _with_eval_cursor(config: dict):
    alias = alias_from_connection_config(config)
    database = str(config.get("database") or "").strip() or None
    close_old_connections()
    return db_alias_session(alias, database=database)


def _db_vendor(cursor) -> str:
    """Django DatabaseWrapper.vendor, or infer from raw driver connection."""
    conn = cursor.connection
    vendor = getattr(conn, "vendor", None)
    if vendor:
        return str(vendor)
    db = getattr(cursor, "db", None)
    if db is not None and getattr(db, "vendor", None):
        return str(db.vendor)
    mod = (type(conn).__module__ or "").lower()
    if "sqlite" in mod:
        return "sqlite"
    if "mysql" in mod or "pymysql" in mod or "mariadb" in mod:
        return "mysql"
    return "unknown"


def _table_columns(cursor) -> set[str]:
    if _db_vendor(cursor) == "mysql":
        cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
            """,
            [MATCH_TABLE],
        )
        return {str(r[0]) for r in cursor.fetchall()}
    # sqlite / tests
    cursor.execute(f"PRAGMA table_info(`{MATCH_TABLE}`)")
    return {str(r[1]) for r in cursor.fetchall()}


def _count_usable(cursor, column: str, *, dataset_code: str | None = None) -> dict[str, int]:
    col = _quote_ident(column)
    where = [f"{col} IS NOT NULL", "`sameflag` IN (0, 1)"]
    params: list[Any] = []
    if dataset_code:
        where.append("`data_set_code` = %s")
        params.append(dataset_code)
    # Numeric-only rows (AlgVersion may be varchar)
    if _db_vendor(cursor) == "mysql":
        where.append(f"CAST({col} AS CHAR) REGEXP '^-?[0-9]+(\\\\.[0-9]+)?$'")
    sql = (
        f"SELECT "
        f"SUM(CASE WHEN `sameflag`=1 THEN 1 ELSE 0 END), "
        f"SUM(CASE WHEN `sameflag`=0 THEN 1 ELSE 0 END), "
        f"COUNT(*) "
        f"FROM `{MATCH_TABLE}` WHERE " + " AND ".join(where)
    )
    cursor.execute(sql, params)
    row = cursor.fetchone() or (0, 0, 0)
    genuine = int(row[0] or 0)
    impostor = int(row[1] or 0)
    total = int(row[2] or 0)
    return {"genuine": genuine, "impostor": impostor, "total": total}


def discover_score_columns(config: dict, *, dataset_code: str | None = None) -> list[dict]:
    """Return score columns that have genuine+impostor numeric data."""
    try:
        with _with_eval_cursor(config) as session_alias:
            conn = connections[session_alias]
            with conn.cursor() as cursor:
                existing = _table_columns(cursor)
                items: list[dict] = []
                for col, label in SCORE_COLUMN_CANDIDATES:
                    if col not in existing:
                        continue
                    try:
                        counts = _count_usable(cursor, col, dataset_code=dataset_code)
                    except Exception:
                        logger.warning("score column scan failed col=%s", col, exc_info=True)
                        continue
                    if counts["genuine"] < _MIN_PAIR_COUNT or counts["impostor"] < _MIN_PAIR_COUNT:
                        continue
                    items.append(
                        {
                            "column": col,
                            "label": label,
                            "genuine_count": counts["genuine"],
                            "impostor_count": counts["impostor"],
                            "total_count": counts["total"],
                            "is_default": col == "score",
                        }
                    )
                return items
    except ExternalDbError as exc:
        raise BizEvalError(str(exc)) from exc
    except BizEvalError:
        raise
    except Exception as exc:
        logger.exception("discover_score_columns failed")
        raise BizEvalError(f"扫描分数列失败: {exc}") from exc


def list_eval_datasets(config: dict) -> list[str]:
    try:
        with _with_eval_cursor(config) as session_alias:
            conn = connections[session_alias]
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT DISTINCT `data_set_code`
                    FROM `{MATCH_TABLE}`
                    WHERE `data_set_code` IS NOT NULL AND `data_set_code` <> ''
                      AND `sameflag` IN (0, 1)
                    ORDER BY `data_set_code`
                    """
                )
                return [str(r[0]).strip() for r in cursor.fetchall() if r and r[0]]
    except ExternalDbError as exc:
        raise BizEvalError(str(exc)) from exc
    except Exception as exc:
        logger.exception("list_eval_datasets failed")
        raise BizEvalError(f"读取数据集失败: {exc}") from exc


def list_eval_meta(config: dict) -> dict:
    datasets = list_eval_datasets(config)
    # Global column discovery (any dataset); UI may re-scan per dataset.
    columns = discover_score_columns(config, dataset_code=None)
    return {
        "match_table": MATCH_TABLE,
        "datasets": datasets,
        "score_columns": columns,
        "sameflag": {"genuine": 1, "impostor": 0},
        "skipped_metrics": [
            "REJenroll",
            "REJnga",
            "REJnira",
            "Avg Enroll Time",
            "Avg Model Size",
            "Max Model Size",
            "Max Enroll Memory",
            "Max Match Memory",
        ],
    }


def _fetch_scores(
    cursor,
    *,
    dataset_code: str,
    column: str,
) -> tuple[list[float], list[float]]:
    col = _quote_ident(column)
    if _db_vendor(cursor) == "mysql":
        sql = (
            f"SELECT CAST({col} AS DECIMAL(24,10)), `sameflag` "
            f"FROM `{MATCH_TABLE}` "
            f"WHERE `data_set_code`=%s AND `sameflag` IN (0,1) AND {col} IS NOT NULL "
            f"AND CAST({col} AS CHAR) REGEXP '^-?[0-9]+(\\\\.[0-9]+)?$'"
        )
    else:
        sql = (
            f"SELECT CAST({col} AS REAL), `sameflag` "
            f"FROM `{MATCH_TABLE}` "
            f"WHERE `data_set_code`=%s AND `sameflag` IN (0,1) AND {col} IS NOT NULL"
        )
    cursor.execute(sql, [dataset_code])
    genuine: list[float] = []
    impostor: list[float] = []
    for score, flag in cursor.fetchall():
        try:
            value = float(score)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        if int(flag) == 1:
            genuine.append(value)
        else:
            impostor.append(value)
    return genuine, impostor


def _fmr_fnmr_at(threshold: float, genuine_sorted: list[float], impostor_sorted: list[float]) -> tuple[float, float]:
    """Accept when score >= threshold."""
    n_g = len(genuine_sorted)
    n_i = len(impostor_sorted)
    # genuine < t → rejected
    fnmr = bisect_left(genuine_sorted, threshold) / n_g if n_g else 0.0
    # impostor >= t → false accept
    fmr = (n_i - bisect_left(impostor_sorted, threshold)) / n_i if n_i else 0.0
    return fmr, fnmr


def _build_curve(
    genuine: list[float],
    impostor: list[float],
    *,
    max_points: int = 200,
) -> list[dict]:
    g = sorted(genuine)
    i = sorted(impostor)
    candidates = sorted(set(g + i))
    if not candidates:
        return []
    if len(candidates) > max_points:
        step = max(1, len(candidates) // max_points)
        candidates = candidates[::step]
        if candidates[-1] != sorted(set(g + i))[-1]:
            candidates.append(sorted(set(g + i))[-1])
    points = []
    for t in candidates:
        fmr, fnmr = _fmr_fnmr_at(t, g, i)
        points.append({"threshold": t, "fmr": fmr, "fnmr": fnmr})
    return points


def _eer_from_curve(points: list[dict]) -> tuple[float, float, float]:
    """Return (eer, threshold, |fmr-fnmr|)."""
    if not points:
        return 0.0, 0.0, 0.0
    best = min(points, key=lambda p: abs(p["fmr"] - p["fnmr"]))
    eer = (best["fmr"] + best["fnmr"]) / 2.0
    return eer, float(best["threshold"]), abs(best["fmr"] - best["fnmr"])


def _fnmr_at_target_fmr(points: list[dict], target_fmr: float) -> float | None:
    """FNMR at the operating point where FMR is closest to (and preferably ≤) target."""
    if not points:
        return None
    eligible = [p for p in points if p["fmr"] <= target_fmr + 1e-12]
    if eligible:
        # among FMR<=target, pick closest to target (largest FMR)
        pick = max(eligible, key=lambda p: p["fmr"])
        return float(pick["fnmr"])
    pick = min(points, key=lambda p: abs(p["fmr"] - target_fmr))
    return float(pick["fnmr"])


def _zero_fmr(genuine: list[float], impostor: list[float]) -> float | None:
    if not genuine or not impostor:
        return None
    t = max(impostor) + 1e-12
    g = sorted(genuine)
    i = sorted(impostor)
    _, fnmr = _fmr_fnmr_at(t, g, i)
    return fnmr


def _zero_fnmr(genuine: list[float], impostor: list[float]) -> float | None:
    if not genuine or not impostor:
        return None
    t = min(genuine)
    g = sorted(genuine)
    i = sorted(impostor)
    fmr, _ = _fmr_fnmr_at(t, g, i)
    return fmr


def _eer_ci(eer: float, n_g: int, n_i: int) -> tuple[float, float]:
    """Rough normal approx CI (not bootstrap)."""
    n = max(1, n_g + n_i)
    # conservative SE using combined sample
    se = math.sqrt(max(eer * (1.0 - eer), 1e-16) * (1.0 / max(n_g, 1) + 1.0 / max(n_i, 1)) / 4.0)
    lo = max(0.0, eer - 1.96 * se)
    hi = min(1.0, eer + 1.96 * se)
    return lo, hi


def _histogram(genuine: list[float], impostor: list[float], bins: int = 40) -> dict:
    all_scores = genuine + impostor
    if not all_scores:
        return {"bins": [], "genuine": [], "impostor": []}
    lo = min(all_scores)
    hi = max(all_scores)
    if hi <= lo:
        hi = lo + 1.0
    width = (hi - lo) / bins
    edges = [lo + i * width for i in range(bins + 1)]
    g_counts = [0] * bins
    i_counts = [0] * bins
    for s in genuine:
        idx = min(bins - 1, max(0, int((s - lo) / width)))
        g_counts[idx] += 1
    for s in impostor:
        idx = min(bins - 1, max(0, int((s - lo) / width)))
        i_counts[idx] += 1
    centers = [(edges[i] + edges[i + 1]) / 2 for i in range(bins)]
    return {
        "bin_edges": edges,
        "bin_centers": centers,
        "genuine": g_counts,
        "impostor": i_counts,
    }


def _pct(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 100.0, 6)


def compute_report(genuine: list[float], impostor: list[float]) -> dict:
    n_g = len(genuine)
    n_i = len(impostor)
    if n_g < _MIN_PAIR_COUNT or n_i < _MIN_PAIR_COUNT:
        raise BizEvalError(
            f"样本不足：Genuine={n_g}, Impostor={n_i}（至少各 {_MIN_PAIR_COUNT}）"
        )

    curve = _build_curve(genuine, impostor)
    eer, eer_t, eer_gap = _eer_from_curve(curve)
    eer_lo, eer_hi = _eer_ci(eer, n_g, n_i)

    accuracy = {
        "eer": _pct(eer),
        "eer_ci": [_pct(eer_lo), _pct(eer_hi)],
        "eer_threshold": eer_t,
        "eer_gap": eer_gap,
        "fmr100": _pct(_fnmr_at_target_fmr(curve, 0.01)),
        "fmr1000": _pct(_fnmr_at_target_fmr(curve, 0.001)),
        "fmr10000": _pct(_fnmr_at_target_fmr(curve, 0.0001)),
        "zero_fmr": _pct(_zero_fmr(genuine, impostor)),
        "zero_fnmr": _pct(_zero_fnmr(genuine, impostor)),
    }

    # Downsample curve for charts
    chart_curve = curve
    if len(chart_curve) > 120:
        step = max(1, len(chart_curve) // 120)
        chart_curve = chart_curve[::step]

    det = [
        {
            "fmr": p["fmr"],
            "fnmr": p["fnmr"],
            "fmr_pct": _pct(p["fmr"]),
            "fnmr_pct": _pct(p["fnmr"]),
            "threshold": p["threshold"],
        }
        for p in chart_curve
    ]

    fmr_fnmr = [
        {
            "threshold": p["threshold"],
            "fmr_pct": _pct(p["fmr"]),
            "fnmr_pct": _pct(p["fnmr"]),
        }
        for p in chart_curve
    ]

    return {
        "counts": {"genuine": n_g, "impostor": n_i, "total": n_g + n_i},
        "accuracy": accuracy,
        "charts": {
            "score_distribution": _histogram(genuine, impostor),
            "fmr_fnmr": fmr_fnmr,
            "det": det,
        },
        "notes": {
            "accept_rule": "score >= threshold",
            "sameflag": "1=Genuine, 0=Impostor",
            "units": "accuracy values are percentages",
        },
    }


def build_eval_report(config: dict, *, dataset_code: str, score_column: str) -> dict:
    dataset_code = (dataset_code or "").strip()
    score_column = (score_column or "score").strip()
    if not dataset_code:
        raise BizEvalError("请选择 data_set_code")
    allowed = {c for c, _ in SCORE_COLUMN_CANDIDATES}
    if score_column not in allowed:
        raise BizEvalError(f"不支持的分数列: {score_column}")
    if len(dataset_code) > 255:
        raise BizEvalError("data_set_code 过长")

    try:
        with _with_eval_cursor(config) as session_alias:
            conn = connections[session_alias]
            with conn.cursor() as cursor:
                existing = _table_columns(cursor)
                if score_column not in existing:
                    raise BizEvalError(f"表中不存在列: {score_column}")
                genuine, impostor = _fetch_scores(
                    cursor, dataset_code=dataset_code, column=score_column
                )
    except BizEvalError:
        raise
    except ExternalDbError as exc:
        raise BizEvalError(str(exc)) from exc
    except Exception as exc:
        logger.exception("build_eval_report failed")
        raise BizEvalError(f"读取比对分数失败: {exc}") from exc

    report = compute_report(genuine, impostor)
    labels = dict(SCORE_COLUMN_CANDIDATES)
    report["meta"] = {
        "dataset_code": dataset_code,
        "score_column": score_column,
        "score_label": labels.get(score_column, score_column),
        "match_table": MATCH_TABLE,
        "algorithm_title": f"{labels.get(score_column, score_column)} on {dataset_code}",
    }
    return report


def parse_eval_connection_params(**kwargs) -> dict:
    cfg = parse_biz_connection_params(**kwargs)
    if cfg.get("connection_id") is not None and not cfg.get("database"):
        cfg["database"] = DEFAULT_DATABASE
    return cfg
