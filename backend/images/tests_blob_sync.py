"""Unit tests for BLOB sync helpers."""
from __future__ import annotations

from django.test import SimpleTestCase

from images.blob_sync_constants import SYNC_STATUS_CHANGED, SYNC_STATUS_IN_SYNC, SYNC_STATUS_MISSING
from images.blob_sync_detect import detect_change_track_mode
from images.blob_sync_service import classify_sync_status


class BlobSyncDetectTests(SimpleTestCase):
    def test_detect_timestamp_column(self):
        mode, col = detect_change_track_mode({"id", "updated_at", "photo"})
        self.assertEqual(mode, "timestamp")
        self.assertEqual(col, "updated_at")

    def test_detect_hash_when_no_timestamp(self):
        mode, col = detect_change_track_mode({"id", "photo", "title"})
        self.assertEqual(mode, "hash")
        self.assertEqual(col, "")


class BlobSyncClassifyTests(SimpleTestCase):
    def test_missing_remote(self):
        status = classify_sync_status(
            remote=None,
            stored_hash="abc",
            stored_length=10,
            local_file_hash="abc",
        )
        self.assertEqual(status, SYNC_STATUS_MISSING)

    def test_in_sync_by_stored_hash(self):
        status = classify_sync_status(
            remote=(100, "deadbeef"),
            stored_hash="deadbeef",
            stored_length=100,
            local_file_hash="",
        )
        self.assertEqual(status, SYNC_STATUS_IN_SYNC)

    def test_changed_when_hash_differs(self):
        status = classify_sync_status(
            remote=(100, "newhash"),
            stored_hash="oldhash",
            stored_length=100,
            local_file_hash="oldhash",
        )
        self.assertEqual(status, SYNC_STATUS_CHANGED)
