"""Fingerprint pair API tests (sqlite)."""
from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.hashers import make_password
from django.db import connection
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
"""


def make_bmp_bytes(name: str, size=(64, 64), color=(200, 200, 200)) -> tuple[str, bytes]:
    buf = io.BytesIO()
    Image.new("L", size, color=color[0] if isinstance(color, tuple) else color).save(buf, format="BMP")
    return name, buf.getvalue()


def make_pair_zip() -> bytes:
    left_bmp_name, left_bmp = make_bmp_bytes("100001_right_index.bmp", color=180)
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

    def test_import_zip_list_compare_toggle(self):
        zip_bytes = make_pair_zip()
        upload = SimpleUploadedFile("sample.zip", zip_bytes, content_type="application/zip")
        res = self.client.post(
            "/api/fingerprints/pairs/import-zip/",
            {"file": upload, "algo_version": "1.0"},
            format="multipart",
        )
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["code"], 0)
        self.assertGreaterEqual(res.data["data"]["imported"], 1)
        pair_id = res.data["data"]["items"][0]["pair_id"]
        self.assertEqual(res.data["data"]["items"][0]["layer_count"], 4)

        # templates landed under templates/
        template_files = list((self.project_root / "templates").rglob("*"))
        self.assertTrue(any(p.is_file() for p in template_files))

        listed = self.client.get(
            "/api/fingerprints/pairs/",
            {"finger_position": "right_index", "layer_type": "bidiso", "score_min": 1},
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data["data"]["total"], 1)

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

    def test_version_compare_colors(self):
        zip_bytes = make_pair_zip()
        upload = SimpleUploadedFile("v1.zip", zip_bytes, content_type="application/zip")
        r1 = self.client.post(
            "/api/fingerprints/pairs/import-zip/",
            {"file": upload, "algo_version": "1.0"},
            format="multipart",
        )
        self.assertEqual(r1.status_code, 200, r1.data)
        pair_id = r1.data["data"]["items"][0]["pair_id"]

        from fingerprints.models import FingerprintFeatureLayer
        from fingerprints.services import _decode_and_cache, _save_template
        from fingerprints.layer_config import get_layer_type
        from utils.db_time import fetch_db_now

        content = build_minimal_fmr([(11, 12, 13, 1)])
        info = get_layer_type("bidiso")
        path, suffix, size = _save_template(
            filename="extra.bidiso",
            content=content,
            layer_info=info,
            algo_version="2.0",
        )
        count, cache = _decode_and_cache(content, setlen=0, setang=256)
        FingerprintFeatureLayer.objects.create(
            pair_id=pair_id,
            side="left",
            layer_type="bidiso",
            algo_name="bidiso",
            algo_version="2.0",
            template_path=path,
            file_suffix=suffix,
            file_hash="x",
            file_size=size,
            setlen=0,
            setang=256,
            minutiae_count=count,
            minutiae_json=cache,
            create_time=fetch_db_now(),
        )

        compare = self.client.get(
            f"/api/fingerprints/pairs/{pair_id}/compare/",
            {"layers": "bidiso"},
        )
        colors = {
            (layer["side"], layer["algo_version"]): layer["color"]
            for layer in compare.data["data"]["layers"]
            if layer["side"] == "left"
        }
        self.assertIn(("left", "1.0"), colors)
        self.assertIn(("left", "2.0"), colors)
        self.assertNotEqual(colors[("left", "1.0")], colors[("left", "2.0")])
