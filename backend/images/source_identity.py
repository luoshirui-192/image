"""Stable logical identity for a migrated external table (independent of physical location)."""
from __future__ import annotations

import uuid

SOURCE_UID_LENGTH = 36


def generate_source_uid() -> str:
    return str(uuid.uuid4())


def normalize_source_uid(value: str | None) -> str:
    return (value or "").strip()


def is_valid_source_uid(value: str | None) -> bool:
    text = normalize_source_uid(value)
    if len(text) != SOURCE_UID_LENGTH:
        return False
    try:
        uuid.UUID(text)
    except (TypeError, ValueError):
        return False
    return True


def ensure_source_record_uid(record, *, persist: bool = True) -> str:
    """Assign source_uid on a BlobMigrationSource or BlobTableView when missing."""
    current = normalize_source_uid(getattr(record, "source_uid", ""))
    if is_valid_source_uid(current):
        return current

    uid = generate_source_uid()
    record.source_uid = uid
    if persist and getattr(record, "pk", None):
        record.__class__.objects.filter(pk=record.pk).update(source_uid=uid)
    return uid
