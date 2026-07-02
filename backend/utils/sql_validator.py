"""SQL validation for read-only SELECT queries — Step 13."""
from __future__ import annotations

import re

# Whole-word forbidden DML/DDL/admin keywords (case-insensitive).
FORBIDDEN_KEYWORDS = frozenset({
    "alter", "call", "commit", "create", "database", "deallocate", "delete",
    "drop", "event", "exec", "execute", "function", "grant", "handler", "insert",
    "load", "lock", "merge", "prepare", "procedure", "rename", "replace",
    "revoke", "rollback", "savepoint", "schema", "truncate", "unlock", "update",
    "user", "view",
})

FORBIDDEN_PATTERNS = (
    (re.compile(r";\s*\S", re.IGNORECASE), "不允许执行多条 SQL 语句"),
    (re.compile(r"\binto\s+outfile\b", re.IGNORECASE), "禁止使用 INTO OUTFILE"),
    (re.compile(r"\binto\s+dumpfile\b", re.IGNORECASE), "禁止使用 INTO DUMPFILE"),
    (re.compile(r"\bload_file\s*\(", re.IGNORECASE), "禁止使用 LOAD_FILE"),
    (re.compile(r"\bsleep\s*\(", re.IGNORECASE), "禁止使用 SLEEP"),
    (re.compile(r"\bbenchmark\s*\(", re.IGNORECASE), "禁止使用 BENCHMARK"),
    (re.compile(r"\bfor\s+update\b", re.IGNORECASE), "禁止使用 FOR UPDATE"),
    (re.compile(r"\block\s+in\s+share\s+mode\b", re.IGNORECASE), "禁止使用 LOCK IN SHARE MODE"),
)

SELECT_START_RE = re.compile(r"^\s*select\b", re.IGNORECASE | re.DOTALL)
KEYWORD_RE_TEMPLATE = r"\b{keyword}\b"


class SqlValidationError(Exception):
    """Raised when SQL fails security or syntax policy checks."""


def strip_sql_comments(sql: str) -> str:
    """Remove block and line comments before validation."""
    without_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    without_line = re.sub(r"(?:--|#)[^\n\r]*", " ", without_block)
    return without_line.strip()


def validate_sql(sql: str, *, require_where_for_select_star: bool = False) -> str:
    """
    Validate SQL is a single read-only SELECT statement.

    Returns normalized SQL (stripped) on success.
    Raises SqlValidationError on violation.
    """
    if not sql or not str(sql).strip():
        raise SqlValidationError("SQL 不能为空")

    raw = str(sql).strip()
    if len(raw) > 10000:
        raise SqlValidationError("SQL 长度超过限制（10000 字符）")

    cleaned = strip_sql_comments(raw)
    if not cleaned:
        raise SqlValidationError("SQL 不能为空")

    if not SELECT_START_RE.match(cleaned):
        raise SqlValidationError("仅允许执行 SELECT 查询语句")

    normalized_lower = cleaned.lower()

    for pattern, message in FORBIDDEN_PATTERNS:
        if pattern.search(cleaned):
            raise SqlValidationError(message)

    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(KEYWORD_RE_TEMPLATE.format(keyword=keyword), normalized_lower):
            raise SqlValidationError(f"禁止使用的 SQL 关键字: {keyword.upper()}")

    if require_where_for_select_star and _is_select_star_without_where(normalized_lower):
        raise SqlValidationError("SELECT * 必须包含 WHERE 条件")

    return cleaned


def _is_select_star_without_where(sql_lower: str) -> bool:
    """Detect SELECT * (or tbl.*) without WHERE clause."""
    if not re.search(r"select\s+\*", sql_lower):
        return False
    return not re.search(r"\bwhere\b", sql_lower)
