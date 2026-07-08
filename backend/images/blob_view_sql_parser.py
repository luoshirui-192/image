"""Parse SQL VIEW definitions to infer per-BLOB path lookup mappings."""
from __future__ import annotations

import re
from dataclasses import dataclass

# `table` `alias` after FROM / JOIN
TABLE_ALIAS_RE = re.compile(
    r"(?:FROM|JOIN)\s+`?(?P<table>[a-zA-Z_][a-zA-Z0-9_]*)`?\s+`?(?P<alias>[a-zA-Z_][a-zA-Z0-9_]*)`?",
    re.IGNORECASE,
)

# `alias`.`col` AS `view_col`  (view_col optional — defaults to col)
SELECT_ITEM_RE = re.compile(
    r"`?(?P<src_alias>[a-zA-Z_][a-zA-Z0-9_]*)`?\.\s*`?(?P<src_col>[a-zA-Z_][a-zA-Z0-9_]*)`?"
    r"(?:\s+AS\s+`?(?P<view_col>[a-zA-Z_][a-zA-Z0-9_]*)`?)?",
    re.IGNORECASE,
)

JOIN_ON_RE = re.compile(
    r"`?(?P<left_alias>[a-zA-Z_][a-zA-Z0-9_]*)`?\.\s*`?(?P<left_col>[a-zA-Z_][a-zA-Z0-9_]*)`?\s*="
    r"\s*(?:\(\s*)?`?(?P<right_alias>[a-zA-Z_][a-zA-Z0-9_]*)`?\.\s*`?(?P<right_col>[a-zA-Z_][a-zA-Z0-9_]*)`?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class JoinCondition:
    left_alias: str
    left_col: str
    right_alias: str
    right_col: str


def normalize_view_sql(sql: str) -> str:
    text = (sql or "").strip()
    text = re.sub(r"\s+COLLATE\s+[a-zA-Z0-9_]+", "", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def split_select_from(sql: str) -> tuple[str, str]:
    normalized = normalize_view_sql(sql)
    match = re.search(r"\bSELECT\b", normalized, re.IGNORECASE)
    if not match:
        return "", normalized
    start = match.end()
    from_match = re.search(r"\bFROM\b", normalized[start:], re.IGNORECASE)
    if not from_match:
        return normalized[start:].strip(), ""
    select_part = normalized[start : start + from_match.start()].strip()
    rest = normalized[start + from_match.start() :].strip()
    return select_part, rest


def parse_table_aliases(from_and_joins: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for match in TABLE_ALIAS_RE.finditer(from_and_joins or ""):
        table = match.group("table")
        alias = match.group("alias")
        if table and alias:
            aliases[alias] = table
    return aliases


def parse_select_columns(select_part: str) -> dict[str, tuple[str, str]]:
    """Map view column name -> (source alias, source column)."""
    mapping: dict[str, tuple[str, str]] = {}
    if not select_part:
        return mapping
    for chunk in _split_select_items(select_part):
        match = SELECT_ITEM_RE.search(chunk)
        if not match:
            continue
        src_alias = match.group("src_alias")
        src_col = match.group("src_col")
        view_col = match.group("view_col") or src_col
        mapping[view_col] = (src_alias, src_col)
    return mapping


def parse_join_conditions(from_and_joins: str) -> list[JoinCondition]:
    conditions: list[JoinCondition] = []
    for match in JOIN_ON_RE.finditer(from_and_joins or ""):
        conditions.append(
            JoinCondition(
                left_alias=match.group("left_alias"),
                left_col=match.group("left_col"),
                right_alias=match.group("right_alias"),
                right_col=match.group("right_col"),
            )
        )
    return conditions


def infer_blob_column_path_mappings(
    view_definition: str,
    blob_columns: list[str],
) -> list[dict[str, str]]:
    """
    Infer image_source_map lookup rules for each BLOB column in a SQL VIEW.

    Returns list of:
      view_column, lookup_table, source_id_column, source_column
    """
    select_part, from_part = split_select_from(view_definition)
    if not select_part or not from_part:
        return []

    table_aliases = parse_table_aliases(from_part)
    select_map = parse_select_columns(select_part)
    joins = parse_join_conditions(from_part)
    if not table_aliases or not select_map:
        return []

    main_alias = _first_from_alias(from_part)
    reverse_select: dict[tuple[str, str], str] = {
        (src_alias, src_col): view_col for view_col, (src_alias, src_col) in select_map.items()
    }

    results: list[dict[str, str]] = []
    for view_col in blob_columns:
        src = select_map.get(view_col)
        if not src:
            continue
        src_alias, src_col = src
        lookup_table = table_aliases.get(src_alias)
        if not lookup_table:
            continue
        source_id_column = _resolve_source_id_column(
            src_alias=src_alias,
            joins=joins,
            main_alias=main_alias,
            reverse_select=reverse_select,
        )
        if not source_id_column:
            continue
        results.append(
            {
                "view_column": view_col,
                "lookup_table": lookup_table,
                "source_id_column": source_id_column,
                "source_column": src_col,
            }
        )
    return results


def _first_from_alias(from_and_joins: str) -> str | None:
    match = re.search(
        r"\bFROM\s+`?(?P<table>[a-zA-Z_][a-zA-Z0-9_]*)`?\s+`?(?P<alias>[a-zA-Z_][a-zA-Z0-9_]*)`?",
        from_and_joins or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    return match.group("alias")


def _resolve_source_id_column(
    *,
    src_alias: str,
    joins: list[JoinCondition],
    main_alias: str | None,
    reverse_select: dict[tuple[str, str], str],
) -> str | None:
    """Pick the view column whose value matches image_source_map.source_id."""
    for join in joins:
        if src_alias not in (join.left_alias, join.right_alias):
            continue
        if join.left_alias == src_alias:
            other_alias, other_col = join.right_alias, join.right_col
        else:
            other_alias, other_col = join.left_alias, join.left_col

        view_col = reverse_select.get((other_alias, other_col))
        if view_col:
            return view_col

        if main_alias and other_alias == main_alias:
            view_col = reverse_select.get((main_alias, other_col))
            if view_col:
                return view_col
    return None


def _split_select_items(select_part: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    depth = 0
    for char in select_part:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            piece = "".join(current).strip()
            if piece:
                items.append(piece)
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        items.append(tail)
    return items
