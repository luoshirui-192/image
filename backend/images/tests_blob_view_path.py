"""Tests for SQL VIEW path lookup helpers (PR2)."""
from __future__ import annotations

from django.test import SimpleTestCase

from images.blob_view_path_service import parse_simple_view_base_table
from images.blob_view_sql_parser import infer_blob_column_path_mappings


JOIN_VIEW_SQL = (
    "select `a`.`Araname` AS `Araname`,`a`.`Arcname` AS `Arcname`,"
    "`a`.`Matchname` AS `Matchname`,`a`.`MatchTime` AS `MatchTime`,"
    "`b`.`image_data` AS `image_data`,`d`.`image_data` AS `imagedataArc`,"
    "`c`.`image_content` AS `image_content` from (((`wgr_1vn_ara_arc` `a` "
    "join `t_images_SAXCreg` `b` on((`b`.`Fname` = `a`.`Araname`))) join "
    "`t_images_SAXCreg` `d` on((`d`.`Fname` = `a`.`Arcname`))) join "
    "`wgr_face_images` `c` on((`c`.`file_name` = `a`.`Matchname`)))"
)

JOIN_VIEW_SQL_WITH_AS = (
    "select `a`.`Araname` AS `Araname`,`a`.`Arcname` AS `Arcname`,"
    "`a`.`Matchname` AS `Matchname`,`b`.`image_data` AS `image_data`,"
    "`d`.`image_data` AS `imagedataArc`,`c`.`image_content` AS `image_content` "
    "from (((`wgr_1vn_ara_arc` as `a` join `t_images_SAXCreg` as `b` "
    "on((`b`.`Fname` = `a`.`Araname`))) join `t_images_SAXCreg` as `d` "
    "on((`d`.`Fname` = `a`.`Arcname`))) join `wgr_face_images` as `c` "
    "on((`c`.`file_name` = `a`.`Matchname`)))"
)

JOIN_VIEW_SQL_TABLE_NAMES = (
    "select `wgr_1vn_ara_arc`.`Araname` AS `Araname`,"
    "`a`.`Matchname` AS `Matchname`,"
    "`t_images_SAXCreg`.`image_data` AS `image_data`,"
    "`wgr_face_images`.`image_content` AS `image_content` "
    "from `wgr_1vn_ara_arc` `a` join `t_images_SAXCreg` `b` "
    "on `b`.`Fname` = `a`.`Araname` join `wgr_face_images` `c` "
    "on `c`.`file_name` = `a`.`Matchname`"
)


class BlobViewPathHelperTestCase(SimpleTestCase):
    def test_parse_simple_view_base_table(self):
        definition = "SELECT `id`, `photo` FROM `legacy_photos` WHERE `status` = 1"
        self.assertEqual(parse_simple_view_base_table(definition), "legacy_photos")

    def test_parse_simple_view_rejects_join(self):
        definition = "SELECT a.id FROM photos a JOIN thumbs b ON a.id = b.id"
        self.assertIsNone(parse_simple_view_base_table(definition))

    def test_infer_join_view_blob_mappings(self):
        blob_columns = ["image_data", "imagedataArc", "image_content"]
        mappings = infer_blob_column_path_mappings(JOIN_VIEW_SQL, blob_columns)
        by_col = {item["view_column"]: item for item in mappings}
        self.assertEqual(len(mappings), 3)

        self.assertEqual(
            by_col["image_data"],
            {
                "view_column": "image_data",
                "lookup_table": "t_images_SAXCreg",
                "source_id_column": "Araname",
                "source_column": "image_data",
            },
        )
        self.assertEqual(
            by_col["imagedataArc"],
            {
                "view_column": "imagedataArc",
                "lookup_table": "t_images_SAXCreg",
                "source_id_column": "Arcname",
                "source_column": "image_data",
            },
        )
        self.assertEqual(
            by_col["image_content"],
            {
                "view_column": "image_content",
                "lookup_table": "wgr_face_images",
                "source_id_column": "Matchname",
                "source_column": "image_content",
            },
        )

    def test_infer_join_view_with_as_keyword(self):
        blob_columns = ["image_data", "imagedataArc", "image_content"]
        mappings = infer_blob_column_path_mappings(JOIN_VIEW_SQL_WITH_AS, blob_columns)
        self.assertEqual(len(mappings), 3)

    def test_infer_join_view_table_names_in_select(self):
        blob_columns = ["image_data", "image_content"]
        mappings = infer_blob_column_path_mappings(JOIN_VIEW_SQL_TABLE_NAMES, blob_columns)
        by_col = {item["view_column"]: item for item in mappings}
        self.assertEqual(len(mappings), 2)
        self.assertEqual(by_col["image_data"]["source_id_column"], "Araname")
        self.assertEqual(by_col["image_content"]["source_id_column"], "Matchname")
