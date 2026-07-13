"""Constants for external BLOB sync."""
from __future__ import annotations

SYNC_STATUS_UNKNOWN = "unknown"
SYNC_STATUS_IN_SYNC = "in_sync"
SYNC_STATUS_CHANGED = "changed"
SYNC_STATUS_MISSING = "missing"
SYNC_STATUS_ERROR = "error"
SYNC_STATUS_PENDING_RESYNC = "pending_resync"

CHANGE_TRACK_HASH = "hash"
CHANGE_TRACK_TIMESTAMP = "timestamp"

RUN_TYPE_DETECT = "detect"
RUN_TYPE_RESYNC = "resync"
RUN_TYPE_BACKFILL = "backfill"

RUN_STATUS_RUNNING = "running"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_FAILED = "failed"

TIMESTAMP_COLUMN_CANDIDATES = (
    "updated_at",
    "update_time",
    "modify_time",
    "modified_at",
    "gmt_modified",
    "last_modified",
    "last_update_time",
)
