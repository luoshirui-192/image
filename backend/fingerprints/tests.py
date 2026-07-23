"""Fingerprint pair API tests (sqlite)."""
from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.hashers import make_password
from django.db import connection, connections
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from fingerprints.iso_decode import build_minimal_fmr, iso_feature_to_minutiae
from fingerprints.layer_config import seed_default_layer_types
from users.models import SysUser

SQLITE_TABLES = """
CREATE TABLE IF NOT EXISTS sys_user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    password VARCHAR(128) NOT NULL,
    username VARCHAR(100) NOT NULL UNIQUE,
    role VARCHAR(20) NOT NULL DEFAULT 'user',
    status SMALLINT NOT NULL DEFAULT 1,
    create_time DATETIME NULL
);
CREATE TABLE IF NOT EXISTS image_category (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_name VARCHAR(100) NOT NULL DEFAULT '',
    sort INTEGER NOT NULL DEFAULT 0,
    create_time DATETIME NULL
);
CREATE TABLE IF NOT EXISTS image_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_name VARCHAR(255) NOT NULL DEFAULT '',
    image_path VARCHAR(500) NOT NULL DEFAULT '',
    image_width INTEGER NOT NULL DEFAULT 0,
    image_height INTEGER NOT NULL DEFAULT 0,
    file_size INTEGER NOT NULL DEFAULT 0,
    file_suffix VARCHAR(20) NOT NULL DEFAULT '',
    file_hash VARCHAR(64) NOT NULL DEFAULT '',
    upload_time DATETIME NOT NULL,
    update_time DATETIME NOT NULL,
    upload_user VARCHAR(100) NOT NULL DEFAULT '',
    is_delete SMALLINT NOT NULL DEFAULT 0,
    category_id INTEGER NULL,
    tags VARCHAR(500) NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS fingerprint_layer_type (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    layer_key VARCHAR(64) NOT NULL UNIQUE,
    label VARCHAR(100) NOT NULL DEFAULT '',
    color VARCHAR(20) NOT NULL DEFAULT '#e53935',
    suffixes VARCHAR(200) NOT NULL DEFAULT '',
    default_algo_name VARCHAR(100) NOT NULL DEFAULT 'default',
    default_setlen INTEGER NOT NULL DEFAULT 0,
    default_setang INTEGER NOT NULL DEFAULT 256,
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled SMALLINT NOT NULL DEFAULT 1,
    create_time DATETIME NULL
);
CREATE TABLE IF NOT EXISTS fingerprint_pair (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_name VARCHAR(200) NOT NULL DEFAULT '',
    finger_position VARCHAR(40) NOT NULL DEFAULT '',
    match_score REAL NULL,
    left_image_id INTEGER NOT NULL DEFAULT 0,
    right_image_id INTEGER NOT NULL DEFAULT 0,
    left_person_id VARCHAR(64) NOT NULL DEFAULT '',
    right_person_id VARCHAR(64) NOT NULL DEFAULT '',
    left_image_name VARCHAR(255) NOT NULL DEFAULT '',
    right_image_name VARCHAR(255) NOT NULL DEFAULT '',
    source_dir VARCHAR(500) NOT NULL DEFAULT '',
    upload_user VARCHAR(100) NOT NULL DEFAULT '',
    tags VARCHAR(500) NOT NULL DEFAULT '',
    is_delete SMALLINT NOT NULL DEFAULT 0,
    create_time DATETIME NULL,
    update_time DATETIME NULL
);
CREATE TABLE IF NOT EXISTS fingerprint_feature_layer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_id INTEGER NOT NULL,
    side VARCHAR(10) NOT NULL DEFAULT 'left',
    layer_type VARCHAR(64) NOT NULL DEFAULT '',
    algo_name VARCHAR(100) NOT NULL DEFAULT 'default',
    algo_version VARCHAR(64) NOT NULL DEFAULT '1.0',
    template_path VARCHAR(500) NOT NULL DEFAULT '',
    file_suffix VARCHAR(40) NOT NULL DEFAULT '',
    file_hash VARCHAR(64) NOT NULL DEFAULT '',
    file_size INTEGER NOT NULL DEFAULT 0,
    setlen INTEGER NOT NULL DEFAULT 0,
    setang INTEGER NOT NULL DEFAULT 256,
    minutiae_count INTEGER NOT NULL DEFAULT 0,
    minutiae_json TEXT,
    create_time DATETIME NULL
);
CREATE TABLE IF NOT EXISTS fingerprint_import_job (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zip_path VARCHAR(500) NOT NULL DEFAULT '',
    zip_name VARCHAR(255) NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    algo_version VARCHAR(64) NOT NULL DEFAULT '1.0',
    tags VARCHAR(500) NOT NULL DEFAULT '',
    skip_existing SMALLINT NOT NULL DEFAULT 1,
    category_id INTEGER NULL,
    total_estimate INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    succeeded INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    cancel_requested SMALLINT NOT NULL DEFAULT 0,
    message VARCHAR(500) NOT NULL DEFAULT '',
    last_error VARCHAR(500) NOT NULL DEFAULT '',
    result_json TEXT NULL,
    created_by VARCHAR(100) NOT NULL DEFAULT '',
    create_time DATETIME NULL,
    started_at DATETIME NULL,
    finished_at DATETIME NULL,
    updated_at DATETIME NULL
);
"""


def make_bmp_bytes(name: str, size=(64, 64), color=(200, 200, 200)) -> tuple[str, bytes]:
    buf = io.BytesIO()
    Image.new("L", size, color=color[0] if isinstance(color, tuple) else color).save(buf, format="BMP")
    return name, buf.getvalue()


def make_pair_zip(*, same_bmp: bool = False) -> bytes:
    left_bmp_name, left_bmp = make_bmp_bytes("100001_right_index.bmp", color=180)
    if same_bmp:
        right_bmp_name, right_bmp = "100002_right_index.bmp", left_bmp
    else:
        right_bmp_name, right_bmp = make_bmp_bytes("100002_right_index.bmp", color=90)
    left_bi = build_minimal_fmr([(20, 30, 40, 1), (50, 60, 80, 2)], width=64, height=64)
    left_ne = build_minimal_fmr([(22, 31, 41, 1)], width=64, height=64)
    right_bi = build_minimal_fmr([(25, 35, 45, 1)], width=64, height=64)
    right_ne = build_minimal_fmr([(28, 38, 55, 2), (40, 41, 10, 1)], width=64, height=64)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        base = "101-1.5/"
        zf.writestr(base + left_bmp_name, left_bmp)
        zf.writestr(base + "100001_right_index.Bidiso", left_bi)
        zf.writestr(base + "100001_right_index.neuiso", left_ne)
        zf.writestr(base + right_bmp_name, right_bmp)
        zf.writestr(base + "100002_right_index.Bidiso", right_bi)
        zf.writestr(base + "100002_right_index.neuiso", right_ne)
    return buf.getvalue()


class IsoDecodeTestCase(TestCase):
    def test_setlen0_setang256(self):
        raw = build_minimal_fmr([(100, 200, 128, 1)], width=400, height=400)
        result = iso_feature_to_minutiae(raw, setlen=0, setang=256)
        self.assertEqual(result.count, 1)
        self.assertEqual(result.minutiae[0].x, 100)
        self.assertEqual(result.minutiae[0].y, 200)
        self.assertEqual(result.minutiae[0].d, 360 - 128 * 360 // 256)


@override_settings(STORAGE_BACKEND="local")
class FingerprintAPITestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._temp_dir = tempfile.TemporaryDirectory()
        cls.project_root = Path(cls._temp_dir.name)
        cls.upload_root = cls.project_root / "upload"
        cls.upload_root.mkdir(parents=True)
        (cls.project_root / "templates").mkdir(parents=True)
        with connection.cursor() as cursor:
            cursor.executescript(SQLITE_TABLES)

    @classmethod
    def tearDownClass(cls):
        cls._temp_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.client = APIClient()
        self.user = SysUser.objects.create(
            username="fpuser",
            password=make_password("pass123"),
            role="user",
            status=1,
        )
        self.admin = SysUser.objects.create(
            username="fpadmin",
            password=make_password("pass123"),
            role="admin",
            status=1,
        )
        self.client.force_authenticate(user=self.user)
        seed_default_layer_types()
        self.settings_ctx = override_settings(
            UPLOAD_ROOT=str(self.upload_root),
            STORAGE_BACKEND="local",
            MAX_UPLOAD_SIZE_BYTES=20 * 1024 * 1024,
        )
        self.settings_ctx.enable()
        from utils.storage import reset_image_storage_cache

        reset_image_storage_cache()

    def tearDown(self):
        self.settings_ctx.disable()
        from utils.storage import reset_image_storage_cache

        reset_image_storage_cache()

    def test_layer_types_dynamic(self):
        res = self.client.get("/api/fingerprints/layer-types/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["code"], 0)
        keys = {item["layer_key"] for item in res.data["data"]["items"]}
        self.assertIn("bidiso", keys)
        self.assertIn("neuiso", keys)

        self.client.force_authenticate(user=self.admin)
        create = self.client.post(
            "/api/fingerprints/layer-types/",
            {
                "layer_key": "customiso",
                "label": "CustomISO",
                "color": "#43a047",
                "suffixes": "customiso",
                "default_setlen": 0,
                "default_setang": 256,
            },
            format="json",
        )
        self.assertEqual(create.status_code, 201)
        self.client.force_authenticate(user=self.user)
        res2 = self.client.get("/api/fingerprints/layer-types/")
        keys2 = {item["layer_key"] for item in res2.data["data"]["items"]}
        self.assertIn("customiso", keys2)

    def _wait_job(self, job_id: int, timeout: float = 30.0):
        import time

        from fingerprints.models import FingerprintImportJob

        deadline = time.time() + timeout
        while time.time() < deadline:
            job = FingerprintImportJob.objects.get(pk=job_id)
            if job.status in {"completed", "failed", "cancelled"}:
                return job
            time.sleep(0.05)
        raise AssertionError(f"import job {job_id} timed out")

    def _import_zip_async(self, zip_bytes: bytes, name: str = "sample.zip", algo_version: str = "1.0"):
        upload = SimpleUploadedFile(name, zip_bytes, content_type="application/zip")
        res = self.client.post(
            "/api/fingerprints/pairs/import-zip/",
            {"file": upload, "algo_version": algo_version},
            format="multipart",
        )
        self.assertIn(res.status_code, {200, 202}, res.data)
        self.assertEqual(res.data["code"], 0)
        job_id = res.data["data"]["job"]["id"]
        job = self._wait_job(job_id)
        self.assertEqual(job.status, "completed", job.message)
        return job

    def test_import_zip_list_compare_toggle(self):
        zip_bytes = make_pair_zip()
        job = self._import_zip_async(zip_bytes)
        self.assertGreaterEqual(job.succeeded, 1)
        self.assertEqual(job.total_estimate, 1)

        # templates landed under templates/
        template_files = list((self.project_root / "templates").rglob("*"))
        self.assertTrue(any(p.is_file() for p in template_files))

        listed = self.client.get(
            "/api/fingerprints/pairs/",
            {"finger_position": "right_index", "layer_type": "bidiso", "score_min": 1},
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data["data"]["total"], 1)
        pair_id = listed.data["data"]["items"][0]["id"]

        compare = self.client.get(f"/api/fingerprints/pairs/{pair_id}/compare/")
        self.assertEqual(compare.status_code, 200)
        layers = compare.data["data"]["layers"]
        self.assertEqual(len(layers), 4)
        types = {layer["layer_type"] for layer in layers}
        self.assertEqual(types, {"bidiso", "neuiso"})

        only_bidiso = self.client.get(
            f"/api/fingerprints/pairs/{pair_id}/compare/",
            {"layers": "bidiso"},
        )
        self.assertEqual(len(only_bidiso.data["data"]["layers"]), 2)
        for layer in only_bidiso.data["data"]["layers"]:
            self.assertEqual(layer["layer_type"], "bidiso")
            self.assertGreater(layer["minutiae"]["count"], 0)

    def test_version_merge_and_colors(self):
        zip_bytes = make_pair_zip()
        job1 = self._import_zip_async(zip_bytes, name="v1.zip", algo_version="1.0")
        self.assertGreaterEqual(job1.succeeded, 1)

        # Same package, new algo_version → merge layers onto existing pair
        job2 = self._import_zip_async(zip_bytes, name="v2.zip", algo_version="2.0")
        self.assertGreaterEqual(job2.succeeded, 1)

        listed = self.client.get("/api/fingerprints/pairs/")
        self.assertEqual(listed.data["data"]["total"], 1)
        pair_id = listed.data["data"]["items"][0]["id"]
        versions = listed.data["data"]["items"][0]["algo_versions"]
        self.assertEqual(sorted(versions), ["1.0", "2.0"])

        # Same version again → skipped
        job3 = self._import_zip_async(zip_bytes, name="v1b.zip", algo_version="1.0")
        self.assertGreaterEqual(job3.skipped, 1)

        compare = self.client.get(
            f"/api/fingerprints/pairs/{pair_id}/compare/",
            {"layers": "bidiso"},
        )
        colors = {
            (layer["side"], layer["algo_version"]): layer["color"]
            for layer in compare.data["data"]["layers"]
            if layer["side"] == "left" and layer["layer_type"] == "bidiso"
        }
        self.assertIn(("left", "1.0"), colors)
        self.assertIn(("left", "2.0"), colors)
        self.assertNotEqual(colors[("left", "1.0")], colors[("left", "2.0")])

    def test_layer_type_patch(self):
        self.client.force_authenticate(user=self.admin)
        listed = self.client.get("/api/fingerprints/layer-types/", {"enabled_only": "0"})
        bidiso = next(i for i in listed.data["data"]["items"] if i["layer_key"] == "bidiso")
        res = self.client.patch(
            f"/api/fingerprints/layer-types/{bidiso['id']}/",
            {"label": "BidisoV2", "color": "#ff0000"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["data"]["label"], "BidisoV2")

    def test_duplicate_report_warn_mode(self):
        """Same left/right bmp content → report pair_same_bmp but still import (default)."""
        zip_bytes = make_pair_zip(same_bmp=True)
        job = self._import_zip_async(zip_bytes, name="dup.bmp.zip")
        self.assertGreaterEqual(job.succeeded, 1)
        detail = self.client.get(f"/api/fingerprints/import-jobs/{job.id}/")
        self.assertEqual(detail.status_code, 200)
        report = detail.data["data"]["duplicate_report"]
        self.assertIsNotNone(report)
        self.assertGreaterEqual(report["total"], 1)
        types = {w["type"] for w in report["warnings"]}
        self.assertIn("pair_same_bmp", types)
        self.assertIn("zip_duplicate_content", types)

    def test_duplicate_fail_mode_blocks(self):
        zip_bytes = make_pair_zip(same_bmp=True)
        upload = SimpleUploadedFile("strict.zip", zip_bytes, content_type="application/zip")
        res = self.client.post(
            "/api/fingerprints/pairs/import-zip/",
            {"file": upload, "algo_version": "1.0", "fail_on_duplicates": "1"},
            format="multipart",
        )
        self.assertIn(res.status_code, {200, 202}, res.data)
        job_id = res.data["data"]["job"]["id"]
        job = self._wait_job(job_id)
        self.assertEqual(job.status, "failed", job.message)
        detail = self.client.get(f"/api/fingerprints/import-jobs/{job_id}/")
        report = detail.data["data"]["duplicate_report"]
        self.assertGreaterEqual(report["blocking_count"], 1)

    def test_path_writeback_inserts_business_rows(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS T_CAP_FP_DATA (
                    cap_image_id VARCHAR(256) NOT NULL PRIMARY KEY,
                    dataset_code VARCHAR(32) NOT NULL,
                    fingerprint_image BLOB NULL,
                    fingerprint_url VARCHAR(256) NULL,
                    created_by VARCHAR(20) NULL,
                    created_time DATETIME NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS T_FEATURE_RECORD (
                    fp_feature_id VARCHAR(32) NOT NULL PRIMARY KEY,
                    fp_image_id VARCHAR(256) NOT NULL,
                    feature_ara_data VARCHAR(500) NULL,
                    feature_neuro_data VARCHAR(500) NULL,
                    created_by VARCHAR(16) NULL,
                    created_time DATETIME NULL
                )
                """
            )
            cursor.execute("DELETE FROM T_FEATURE_RECORD")
            cursor.execute("DELETE FROM T_CAP_FP_DATA")

        zip_bytes = make_pair_zip()
        job = self._import_zip_async(zip_bytes, name="base.zip")
        self.assertEqual(job.status, "completed", job.message)

        from fingerprints.models import FingerprintPair
        from fingerprints.path_writeback import writeback_import_sides
        from fingerprints import path_writeback as pwb
        from images.models import ImageInfo

        pair = FingerprintPair.objects.filter(is_delete=0).first()
        self.assertIsNotNone(pair)
        left = ImageInfo.objects.get(pk=pair.left_image_id)
        right = ImageInfo.objects.get(pk=pair.right_image_id)

        pwb._SCHEMA_ENSURED.clear()
        pwb._SCHEMA_FAILED.clear()
        try:
            cfg = {
                "enabled": True,
                "db_alias": "default",
                "database": "",
                "dataset_code": "PK_5W",
            }
            wb = writeback_import_sides(
                cfg,
                [
                    {
                        "cap_image_id": "100001_right_index",
                        "image_path": left.image_path,
                        "bidiso_path": "templates/20260101/a.bidiso",
                        "neuiso_path": "templates/20260101/a.neuiso",
                    },
                    {
                        "cap_image_id": "100002_right_index",
                        "image_path": right.image_path,
                        "bidiso_path": "templates/20260101/b.bidiso",
                        "neuiso_path": "templates/20260101/b.neuiso",
                    },
                ],
                created_by="fpuser",
            )
        finally:
            pwb._SCHEMA_ENSURED.clear()

        self.assertEqual(wb.failed, 0, wb.errors)
        self.assertEqual(wb.updated, 2)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT cap_image_id, dataset_code, fingerprint_image FROM T_CAP_FP_DATA ORDER BY cap_image_id"
            )
            caps = cursor.fetchall()
            cursor.execute(
                "SELECT fp_image_id, feature_ara_data, feature_neuro_data FROM T_FEATURE_RECORD ORDER BY fp_image_id"
            )
            feats = cursor.fetchall()
        self.assertEqual(len(caps), 2)
        self.assertEqual(caps[0][0], "100001_right_index")
        self.assertEqual(caps[0][1], "PK_5W")
        blob0 = caps[0][2]
        if isinstance(blob0, memoryview):
            blob0 = blob0.tobytes()
        if isinstance(blob0, bytes):
            blob0 = blob0.decode("utf-8")
        self.assertTrue(str(blob0).startswith("upload/"), blob0)
        self.assertEqual(len(feats), 2)
        self.assertEqual(feats[0][0], "100001_right_index")
        self.assertTrue(str(feats[0][1]).startswith("templates/"))
        self.assertTrue(str(feats[0][2]).startswith("templates/"))

    def test_path_writeback_invalid_config_rejected(self):
        zip_bytes = make_pair_zip()
        upload = SimpleUploadedFile("badwb.zip", zip_bytes, content_type="application/zip")
        bad = {
            "enabled": True,
            "connection_id": "not-a-number",
        }
        res = self.client.post(
            "/api/fingerprints/pairs/import-zip/",
            {
                "file": upload,
                "algo_version": "1.0",
                "path_writeback": __import__("json").dumps(bad),
            },
            format="multipart",
        )
        self.assertEqual(res.status_code, 400)
        self.assertNotEqual(res.data["code"], 0)

    def _ensure_biz_tables(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS T_CAP_FP_DATA (
                    cap_image_id VARCHAR(256) NOT NULL PRIMARY KEY,
                    dataset_code VARCHAR(32) NOT NULL,
                    fingerprint_image BLOB NULL,
                    fingerprint_url VARCHAR(256) NULL,
                    created_by VARCHAR(20) NULL,
                    created_time DATETIME NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS T_FEATURE_RECORD (
                    fp_feature_id VARCHAR(32) NOT NULL PRIMARY KEY,
                    fp_image_id VARCHAR(256) NOT NULL,
                    feature_ara_data VARCHAR(500) NULL,
                    feature_neuro_data VARCHAR(500) NULL,
                    created_by VARCHAR(16) NULL,
                    created_time DATETIME NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS t_match_result_image (
                    id INTEGER NOT NULL PRIMARY KEY,
                    image_reg VARCHAR(200) NULL,
                    image_match VARCHAR(200) NULL,
                    score REAL NULL,
                    algorithm_type VARCHAR(50) NULL,
                    match_time DATETIME NULL,
                    fingerprint_image VARCHAR(500) NOT NULL DEFAULT '',
                    sameflag INTEGER NULL,
                    data_set_code VARCHAR(255) NULL
                )
                """
            )
            cursor.execute("DELETE FROM T_FEATURE_RECORD")
            cursor.execute("DELETE FROM T_CAP_FP_DATA")
            cursor.execute("DELETE FROM t_match_result_image")

    def _seed_cap_side(self, stem: str, *, uuid_img: str, uuid_bi: str, uuid_ne: str):
        from utils.storage import get_image_storage

        img_path = f"upload/20260720/1/{uuid_img}.bmp"
        bi_path = f"templates/20260720/{uuid_bi}.bidiso"
        ne_path = f"templates/20260720/{uuid_ne}.neuiso"
        _, bmp = make_bmp_bytes(f"{stem}.bmp")
        bi = build_minimal_fmr([(10, 20, 30, 1)], width=64, height=64)
        ne = build_minimal_fmr([(11, 21, 31, 1)], width=64, height=64)
        storage = get_image_storage()
        storage.write_bytes(img_path, bmp)
        storage.write_bytes(bi_path, bi)
        storage.write_bytes(ne_path, ne)
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO T_CAP_FP_DATA (cap_image_id, dataset_code, fingerprint_image) "
                "VALUES (%s, %s, %s)",
                [stem, "PK_5W", img_path.encode("utf-8")],
            )
            cursor.execute(
                "INSERT INTO T_FEATURE_RECORD "
                "(fp_feature_id, fp_image_id, feature_ara_data, feature_neuro_data) "
                "VALUES (%s, %s, %s, %s)",
                [uuid_bi.replace("-", "")[:32], stem, bi_path, ne_path],
            )
        return img_path

    def test_biz_browse_list_and_view(self):
        self._ensure_biz_tables()
        self._seed_cap_side(
            "100001_right_index",
            uuid_img="550e8400-e29b-41d4-a716-446655440001",
            uuid_bi="550e8400-e29b-41d4-a716-446655440002",
            uuid_ne="550e8400-e29b-41d4-a716-446655440003",
        )

        listed = self.client.get(
            "/api/fingerprints/biz/samples/",
            {"db_alias": "default", "database": "", "page_size": 50},
        )
        self.assertEqual(listed.status_code, 200, listed.data)
        self.assertEqual(listed.data["code"], 0)
        items = listed.data["data"]["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["cap_image_id"], "100001_right_index")

        view = self.client.get(
            "/api/fingerprints/biz/samples/100001_right_index/view/",
            {"db_alias": "default", "database": ""},
        )
        self.assertEqual(view.status_code, 200, view.data)
        data = view.data["data"]
        self.assertEqual(data["mode"], "single")
        self.assertEqual(len(data["panels"]), 1)
        types = {layer["layer_type"] for layer in data["panels"][0]["layers"]}
        self.assertEqual(types, {"bidiso", "neuiso"})

    def test_biz_browse_empty_feature_paths(self):
        from utils.storage import get_image_storage

        self._ensure_biz_tables()
        img_path = "upload/20260720/1/550e8400-e29b-41d4-a716-446655440011.bmp"
        _, bmp = make_bmp_bytes("y.bmp", color=100)
        get_image_storage().write_bytes(img_path, bmp)
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO T_CAP_FP_DATA (cap_image_id, dataset_code, fingerprint_image) "
                "VALUES (%s, %s, %s)",
                ["only_image", "PK_5W", img_path.encode("utf-8")],
            )
            cursor.execute(
                "INSERT INTO T_FEATURE_RECORD "
                "(fp_feature_id, fp_image_id, feature_ara_data, feature_neuro_data) "
                "VALUES (%s, %s, %s, %s)",
                ["b" * 32, "only_image", None, ""],
            )

        view = self.client.get(
            "/api/fingerprints/biz/samples/only_image/view/",
            {"db_alias": "default", "database": ""},
        )
        self.assertEqual(view.status_code, 200, view.data)
        panel = view.data["data"]["panels"][0]
        self.assertEqual(panel["layers"], [])

    def test_biz_pair_list_and_dual_view(self):
        self._ensure_biz_tables()
        self._seed_cap_side(
            "100001_right_index",
            uuid_img="550e8400-e29b-41d4-a716-446655440021",
            uuid_bi="550e8400-e29b-41d4-a716-446655440022",
            uuid_ne="550e8400-e29b-41d4-a716-446655440023",
        )
        self._seed_cap_side(
            "100002_right_index",
            uuid_img="550e8400-e29b-41d4-a716-446655440024",
            uuid_bi="550e8400-e29b-41d4-a716-446655440025",
            uuid_ne="550e8400-e29b-41d4-a716-446655440026",
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO t_match_result_image "
                "(id, image_reg, image_match, data_set_code, fingerprint_image) "
                "VALUES (%s, %s, %s, %s, %s)",
                [101, "100001_right_index", "100002_right_index", "PK_5W", ""],
            )

        meta = self.client.get(
            "/api/fingerprints/biz/meta/",
            {"db_alias": "default", "database": ""},
        )
        self.assertEqual(meta.status_code, 200, meta.data)
        self.assertIn("PK_5W", meta.data["data"]["dataset_codes"])
        self.assertEqual(meta.data["data"]["match_table"], "t_match_result_image")

        listed = self.client.get(
            "/api/fingerprints/biz/pairs/",
            {"db_alias": "default", "database": "", "dataset_code": "PK_5W"},
        )
        self.assertEqual(listed.status_code, 200, listed.data)
        items = listed.data["data"]["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], 101)
        self.assertEqual(items[0]["image_reg"], "100001_right_index")
        self.assertEqual(items[0]["image_match"], "100002_right_index")
        self.assertNotIn("score", items[0])

        view = self.client.get(
            "/api/fingerprints/biz/pairs/101/view/",
            {"db_alias": "default", "database": ""},
        )
        self.assertEqual(view.status_code, 200, view.data)
        data = view.data["data"]
        self.assertEqual(data["mode"], "pair")
        self.assertEqual(len(data["panels"]), 2)
        self.assertEqual(data["panels"][0]["role"], "reg")
        self.assertEqual(data["panels"][1]["role"], "match")
        self.assertEqual(data["pair_meta"]["id"], 101)
        self.assertEqual(data["pair_meta"]["image_reg"], "100001_right_index")
        self.assertNotIn("score", data["pair_meta"])
        self.assertGreater(data["panels"][0]["layers"][0]["minutiae"]["count"], 0)
        self.assertGreater(data["panels"][1]["layers"][0]["minutiae"]["count"], 0)


class PathWritebackUnitTestCase(TestCase):
    def test_parse_disabled(self):
        from fingerprints.path_writeback import parse_path_writeback_config

        self.assertIsNone(parse_path_writeback_config(None))
        self.assertIsNone(parse_path_writeback_config({"enabled": False}))

    def test_parse_enabled_normalized(self):
        from fingerprints.path_writeback import DEFAULT_DATASET_CODE, parse_path_writeback_config

        cfg = parse_path_writeback_config(
            {
                "enabled": True,
                "db_alias": "default",
            }
        )
        self.assertEqual(cfg["dataset_code"], DEFAULT_DATASET_CODE)
        self.assertEqual(cfg["database"], "ara_fp_analyst")

    def test_writeback_cap_and_feature(self):
        from fingerprints.path_writeback import parse_path_writeback_config, writeback_cap_and_feature

        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS T_CAP_FP_DATA (
                    cap_image_id VARCHAR(256) NOT NULL PRIMARY KEY,
                    dataset_code VARCHAR(32) NOT NULL,
                    fingerprint_image BLOB NULL,
                    fingerprint_url VARCHAR(256) NULL,
                    created_by VARCHAR(20) NULL,
                    created_time DATETIME NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS T_FEATURE_RECORD (
                    fp_feature_id VARCHAR(32) NOT NULL PRIMARY KEY,
                    fp_image_id VARCHAR(256) NOT NULL,
                    feature_ara_data VARCHAR(500) NULL,
                    feature_neuro_data VARCHAR(500) NULL,
                    created_by VARCHAR(16) NULL,
                    created_time DATETIME NULL
                )
                """
            )
            cursor.execute("DELETE FROM T_FEATURE_RECORD")
            cursor.execute("DELETE FROM T_CAP_FP_DATA")

        from fingerprints import path_writeback as pwb

        pwb._SCHEMA_ENSURED.clear()
        pwb._SCHEMA_FAILED.clear()
        try:
            cfg = parse_path_writeback_config(
                {"enabled": True, "db_alias": "default", "database": ""}
            )
            ok = writeback_cap_and_feature(
                cfg,
                cap_image_id="9_right_thumb",
                image_path="upload/20260101/1/a.bmp",
                bidiso_path="templates/20260101/a.bidiso",
                neuiso_path="templates/20260101/a.neuiso",
                created_by="tester",
            )
            self.assertEqual(ok.updated, 1, ok.errors)
            self.assertEqual(ok.failed, 0)

            # idempotent update: missing neuiso must NOT wipe existing path
            ok2 = writeback_cap_and_feature(
                cfg,
                cap_image_id="9_right_thumb",
                image_path="upload/20260101/1/a2.bmp",
                bidiso_path="templates/20260101/a2.bidiso",
                neuiso_path=None,
                created_by="tester",
            )
            self.assertEqual(ok2.updated, 1, ok2.errors)
        finally:
            pwb._SCHEMA_ENSURED.clear()

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT dataset_code, fingerprint_image FROM T_CAP_FP_DATA WHERE cap_image_id=%s",
                ["9_right_thumb"],
            )
            ds, blob = cursor.fetchone()
            cursor.execute(
                "SELECT feature_ara_data, feature_neuro_data FROM T_FEATURE_RECORD WHERE fp_image_id=%s",
                ["9_right_thumb"],
            )
            ara, neuro = cursor.fetchone()
        self.assertEqual(ds, "PK_5W")
        if isinstance(blob, memoryview):
            blob = blob.tobytes()
        if isinstance(blob, bytes):
            blob = blob.decode("utf-8")
        self.assertEqual(blob, "upload/20260101/1/a2.bmp")
        self.assertEqual(ara, "templates/20260101/a2.bidiso")
        self.assertEqual(neuro, "templates/20260101/a.neuiso")

    def test_normalize_relative_path(self):
        from fingerprints.path_writeback import normalize_relative_path

        self.assertEqual(
            normalize_relative_path("data/image_db/upload/2026/a.bmp"),
            "upload/2026/a.bmp",
        )
        self.assertEqual(normalize_relative_path(""), "")
