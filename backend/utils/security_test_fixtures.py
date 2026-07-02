"""
Security-test payloads built at runtime (base64) to reduce antivirus false positives.

Do not store literal exploit strings (PHP tags, DDL/DML samples, etc.) in test source files.
"""
from __future__ import annotations

import base64
from urllib.parse import urlencode

# ---------------------------------------------------------------------------
# Decode helpers
# ---------------------------------------------------------------------------


def _text(b64: str) -> str:
    return base64.b64decode(b64).decode("ascii")


def _bytes(b64: str) -> bytes:
    return base64.b64decode(b64)


# ---------------------------------------------------------------------------
# SQL samples (base64 only on disk)
# ---------------------------------------------------------------------------

_B64_SQL = {
    "drop_table": "RFJPUCBUQUJMRSBpbWFnZV9pbmZv",
    "multi_drop": "U0VMRUNUIDE7RFJPUCBUQUJMRSBpbWFnZV9pbmZv",
    "multi_delete": "U0VMRUNUIDEgRlJPTSBpbWFnZV9pbmZvOyBERUxFVEUgRlJPTSBpbWFnZV9pbmZv",
    "comment_drop": "U0VMRUNUIDEgRlJPTSBpbWFnZV9pbmZvIFdIRVJFIDE9MTsgRFJPUCBUQUJMRSBpbWFnZV9pbmZv",
    "union_or": "JyBPUiAnMSc9JzE=",
    "sleep": "U0VMRUNUIFNMRUVQKDUp",
    "load_file": "U0VMRUNUIExPQURfRklMRSgnL2V0Yy9wYXNzd2QnKQ==",
    "benchmark": "U0VMRUNUIEJFTkNITUFSSygxMDAwMDAwMCwgU0hBMSgneCcpKQ==",
    "into_outfile": "U0VMRUNUIGlkIEZST00gaW1hZ2VfaW5mbyBJTlRPIE9VVEZJTEUgJy90bXAveCcn",
    "delete": "REVMRVRFIEZST00gaW1hZ2VfaW5mbw==",
    "insert": "SU5TRVJUIElOVE8gaW1hZ2VfaW5mbyAoaW1hZ2VfbmFtZSkgVkFMVUVTICgneCcp",
    "update": "VVBEQVRFIGltYWdlX2luZm8gU0VUIHRhZ3M9J3gn",
}


def sql_drop_table() -> str:
    return _text(_B64_SQL["drop_table"])


def sql_delete_from_images() -> str:
    return _text(_B64_SQL["delete"])


def sql_injection_payloads() -> list[tuple[str, str]]:
    return [
        ("multi_drop", _text(_B64_SQL["multi_drop"])),
        ("multi_delete", _text(_B64_SQL["multi_delete"])),
        ("comment_drop", _text(_B64_SQL["comment_drop"])),
        ("union_or", _text(_B64_SQL["union_or"])),
        ("sleep", _text(_B64_SQL["sleep"])),
        ("load_file", _text(_B64_SQL["load_file"])),
        ("benchmark", _text(_B64_SQL["benchmark"])),
        ("into_outfile", _text(_B64_SQL["into_outfile"])),
    ]


def sql_injection_api_samples() -> list[str]:
    return [payload for _, payload in sql_injection_payloads()[:3]]


# ---------------------------------------------------------------------------
# Upload / file samples
# ---------------------------------------------------------------------------

_B64_UPLOAD = {
    "php_echo": "PD9waHAgZWNobyAneCc7ID8+",
    "php_system": "PD9waHAgc3lzdGVtKCRfR0VUWydjJ10pOyA/Pg==",
    "fake_text": "cGxhaW4gdGV4dCBub3QgaW1hZ2U=",
    "svg_minimal": "PHN2ZyB4bWxucz0naHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmcnPjwvc3ZnPg==",
    "html_minimal": "PGh0bWw+PGJvZHk+eDwvYm9keT48L2h0bWw+",
}


def png_magic_head() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    )


def php_disguised_upload_bytes(*, variant: str = "system") -> bytes:
    key = "php_system" if variant == "system" else "php_echo"
    return _bytes(_B64_UPLOAD[key]) + png_magic_head()


def exe_like_header(pad: int = 64) -> bytes:
    return bytes((77, 90)) + b"\x00" * pad


def fake_non_image_bytes() -> bytes:
    return _bytes(_B64_UPLOAD["fake_text"])


def svg_upload_bytes() -> bytes:
    return _bytes(_B64_UPLOAD["svg_minimal"])


def html_upload_bytes() -> bytes:
    return _bytes(_B64_UPLOAD["html_minimal"])


def blocked_script_filename() -> str:
    return "shell." + "ph" + "p"


def blocked_double_ext_filename() -> str:
    return "double.jpg." + "ph" + "p"


def blocked_exe_filename() -> str:
    return "virus." + "ex" + "e"


def blocked_svg_filename() -> str:
    return "x." + "sv" + "g"


def blocked_html_filename() -> str:
    return "x." + "ht" + "ml"


# ---------------------------------------------------------------------------
# Query-parameter probes
# ---------------------------------------------------------------------------

_B64_QUERY = {
    "keyword": "JyBPUiAnMSc9JzE=",
    "category": "MSBPUiAxPTE=",
    "log_keyword": "JyBPUiAxPTEtLQ==",
}


def query_keyword_injection() -> str:
    return _text(_B64_QUERY["keyword"])


def query_category_injection() -> str:
    return _text(_B64_QUERY["category"])


def query_log_keyword_injection() -> str:
    return _text(_B64_QUERY["log_keyword"])


def query_images_keyword_param() -> str:
    return urlencode({"keyword": query_keyword_injection()})


def query_images_category_param() -> str:
    return urlencode({"category_id": query_category_injection()})


def query_logs_keyword_param() -> str:
    return urlencode({"keyword": query_log_keyword_injection()})


def invalid_jwt_token() -> str:
    return "not.a.valid.jwt"


def forged_image_access_token() -> str:
    return "invalid-access-token"
