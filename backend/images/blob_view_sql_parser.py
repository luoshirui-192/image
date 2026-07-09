"""Parse SQL VIEW definitions to infer per-BLOB path lookup mappings."""
from __future__ import annotations

import re
from dataclasses import dataclass

# `schema`.`table` `alias` / `table` AS `alias` after FROM / JOIN (optional parens)
TABLE_ALIAS_RE = re.compile(
    r"(?:FROM|JOIN)\s+"
    r"(?:\(\s*)*"
    r"(?:(?:`?(?P<schema>[a-zA-Z_][a-zA-Z0-9_]*)`?)\.)?"
    r"`?(?P<table>[a-zA-Z_][a-zA-Z0-9_]*)`?\s+"
    r"(?:AS\s+)?"
    r"`?(?P<alias>[a-zA-Z_][a-zA-Z0-9_]*)`?",
    re.IGNORECASE,
)

# `schema`.`ref`.`col` AS `view_col`  (ref = alias or table name)
SELECT_ITEM_RE = re.compile(
    r"(?:(?:`?(?P<sel_schema>[a-zA-Z_][a-zA-Z0-9_]*)`?)\.)?"
    r"`?(?P<src_ref>[a-zA-Z_][a-zA-Z0-9_]*)`?\.\s*"
    r"`?(?P<src_col>[a-zA-Z_][a-zA-Z0-9_]*)`?"
    r"(?:\s+(?:AS\s+)?`?(?P<view_col>[a-zA-Z_][a-zA-Z0-9_]*)`?)?",
    re.IGNORECASE,
)

JOIN_ON_RE = re.compile(
    r"(?:(?:`?(?P<left_schema>[a-zA-Z_][a-zA-Z0-9_]*)`?)\.)?"
    r"`?(?P<left_ref>[a-zA-Z_][a-zA-Z0-9_]*)`?\.\s*"
    r"`?(?P<left_col>[a-zA-Z_][a-zA-Z0-9_]*)`?\s*="
    r"\s*(?:\(\s*)*"
    r"(?:(?:`?(?P<right_schema>[a-zA-Z_][a-zA-Z0-9_]*)`?)\.)?"
    r"`?(?P<right_ref>[a-zA-Z_][a-zA-Z0-9_]*)`?\.\s*"
    r"`?(?P<right_col>[a-zA-Z_][a-zA-Z0-9_]*)`?",
    re.IGNORECASE,
)

DRIVING_TABLE_RE = re.compile(
    r"\bFROM\s+(?:\(\s*)*"
    r"(?:(?:`?(?P<schema>[a-zA-Z_][a-zA-Z0-9_]*)`?)\.)?"
    r"`?(?P<table>[a-zA-Z_][a-zA-Z0-9_]*)`?",
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


def parse_select_columns(select_part: str, alias_to_table: dict[str, str]) -> dict[str, tuple[str, str]]:
    """Map view column name -> (source alias, source column)."""
    mapping: dict[str, tuple[str, str]] = {}
    if not select_part:
        return mapping
    for chunk in _split_select_items(select_part):
        match = SELECT_ITEM_RE.search(chunk)
        if not match:
            continue
        src_ref = match.group("src_ref")
        src_col = match.group("src_col")
        view_col = match.group("view_col") or src_col
        src_alias = _resolve_table_ref(src_ref, alias_to_table)
        mapping[view_col] = (src_alias, src_col)
    return mapping


def parse_join_conditions(from_and_joins: str, alias_to_table: dict[str, str]) -> list[JoinCondition]:
    conditions: list[JoinCondition] = []
    for match in JOIN_ON_RE.finditer(from_and_joins or ""):
        conditions.append(
            JoinCondition(
                left_alias=_resolve_table_ref(match.group("left_ref"), alias_to_table),
                left_col=match.group("left_col"),
                right_alias=_resolve_table_ref(match.group("right_ref"), alias_to_table),
                right_col=match.group("right_col"),
            )
        )
    return conditions


def parse_view_driving_table(view_definition: str) -> str | None:
    _, from_part = split_select_from(view_definition)
    match = DRIVING_TABLE_RE.search(from_part or "")
    if not match:
        return None
    return match.group("table")


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
    select_map = parse_select_columns(select_part, table_aliases)
    joins = parse_join_conditions(from_part, table_aliases)
    if not table_aliases or not select_map:
        return []

    main_alias = _first_from_alias(from_part, table_aliases)
    reverse_select: dict[tuple[str, str], str] = {
        (src_alias, src_col): view_col for view_col, (src_alias, src_col) in select_map.items()
    }

    results: list[dict[str, str]] = []
    for view_col in blob_columns:
        src = select_map.get(view_col)
        if not src:
            continue
        src_alias, src_col = src
        lookup_table = table_aliases.get(src_alias) or src_alias
        source_id_column, lookup_id_column = _resolve_source_id_columns(
            src_alias=src_alias,
            joins=joins,
            main_alias=main_alias,
            reverse_select=reverse_select,
        )
        if not source_id_column or not lookup_id_column:
            continue
        results.append(
            {
                "view_column": view_col,
                "lookup_table": lookup_table,
                "source_id_column": source_id_column,
                "lookup_id_column": lookup_id_column,
                "source_column": src_col,
            }
        )
    return results


def _first_from_alias(from_and_joins: str, alias_to_table: dict[str, str]) -> str | None:
    match = DRIVING_TABLE_RE.search(from_and_joins or "")
    if not match:
        return None
    table = match.group("table")
    for alias, mapped in alias_to_table.items():
        if mapped == table and alias != table:
            return alias
    return table


def _resolve_table_ref(ref: str, alias_to_table: dict[str, str]) -> str:
    if ref in alias_to_table:
        return ref
    matches = [alias for alias, table in alias_to_table.items() if table == ref]
    if len(matches) == 1:
        return matches[0]
    return ref


def _resolve_source_id_columns(
    *,
    src_alias: str,
    joins: list[JoinCondition],
    main_alias: str | None,
    reverse_select: dict[tuple[str, str], str],
) -> tuple[str | None, str | None]:
    """Return (view source_id column, lookup-table id column) for image_source_map.source_id."""
    for join in joins:
        if src_alias not in (join.left_alias, join.right_alias):
            continue
        if join.left_alias == src_alias:
            lookup_id_column = join.left_col
            other_alias, other_col = join.right_alias, join.right_col
        else:
            lookup_id_column = join.right_col
            other_alias, other_col = join.left_alias, join.left_col

        view_col = reverse_select.get((other_alias, other_col))
        if view_col:
            return view_col, lookup_id_column

        if main_alias and other_alias == main_alias:
            view_col = reverse_select.get((main_alias, other_col))
            if view_col:
                return view_col, lookup_id_column
    return None, None


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
