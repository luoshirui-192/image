"""Default / runtime fingerprint layer-type configuration."""
from __future__ import annotations

from dataclasses import dataclass

from fingerprints.iso_decode import DEFAULT_SETANG, DEFAULT_SETLEN
from fingerprints.models import FingerprintLayerType
from utils.db_time import fetch_db_now
from utils.path_builder import normalize_suffix

# Seed rows — adding a type only requires DB/config insert; UI reads API.
DEFAULT_LAYER_TYPE_SEEDS: list[dict] = [
    {
        "layer_key": "bidiso",
        "label": "Bidiso",
        "color": "#e53935",
        "suffixes": "bidiso",
        "default_algo_name": "bidiso",
        "default_setlen": DEFAULT_SETLEN,
        "default_setang": DEFAULT_SETANG,
        "sort_order": 10,
    },
    {
        "layer_key": "neuiso",
        "label": "neuiso",
        "color": "#1e88e5",
        "suffixes": "neuiso",
        "default_algo_name": "neuiso",
        "default_setlen": DEFAULT_SETLEN,
        "default_setang": DEFAULT_SETANG,
        "sort_order": 20,
    },
]


@dataclass(frozen=True)
class LayerTypeInfo:
    layer_key: str
    label: str
    color: str
    suffixes: tuple[str, ...]
    default_algo_name: str
    default_setlen: int
    default_setang: int
    sort_order: int
    enabled: bool
    id: int | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "layer_key": self.layer_key,
            "label": self.label,
            "color": self.color,
            "suffixes": list(self.suffixes),
            "default_algo_name": self.default_algo_name,
            "default_setlen": self.default_setlen,
            "default_setang": self.default_setang,
            "sort_order": self.sort_order,
            "enabled": self.enabled,
        }


def _row_to_info(row: FingerprintLayerType) -> LayerTypeInfo:
    return LayerTypeInfo(
        id=row.id,
        layer_key=row.layer_key,
        label=row.label or row.layer_key,
        color=row.color or "#888888",
        suffixes=tuple(row.suffix_list()),
        default_algo_name=row.default_algo_name or "default",
        default_setlen=int(row.default_setlen),
        default_setang=int(row.default_setang),
        sort_order=int(row.sort_order),
        enabled=bool(row.enabled),
    )


def seed_default_layer_types() -> int:
    """Insert missing default layer types. Returns number of rows created."""
    created = 0
    now = fetch_db_now()
    for seed in DEFAULT_LAYER_TYPE_SEEDS:
        if FingerprintLayerType.objects.filter(layer_key=seed["layer_key"]).exists():
            continue
        FingerprintLayerType.objects.create(create_time=now, enabled=1, **seed)
        created += 1
    return created


def list_layer_types(*, enabled_only: bool = True) -> list[LayerTypeInfo]:
    seed_default_layer_types()
    qs = FingerprintLayerType.objects.all().order_by("sort_order", "id")
    if enabled_only:
        qs = qs.filter(enabled=1)
    return [_row_to_info(row) for row in qs]


def get_layer_type(layer_key: str) -> LayerTypeInfo | None:
    seed_default_layer_types()
    row = FingerprintLayerType.objects.filter(layer_key=layer_key).first()
    return _row_to_info(row) if row else None


def resolve_layer_type_by_suffix(suffix: str) -> LayerTypeInfo | None:
    ext = normalize_suffix(suffix)
    for info in list_layer_types(enabled_only=True):
        if ext in info.suffixes:
            return info
    return None


def allowed_template_suffixes() -> set[str]:
    suffixes: set[str] = set()
    for info in list_layer_types(enabled_only=True):
        suffixes.update(info.suffixes)
    return suffixes


def version_color(base_color: str, algo_version: str, siblings: list[str]) -> str:
    """Derive a distinct color for same layer_type across versions."""
    if len(siblings) <= 1:
        return base_color
    palette = [
        base_color,
        "#43a047",
        "#fb8c00",
        "#8e24aa",
        "#00897b",
        "#6d4c41",
    ]
    try:
        idx = siblings.index(algo_version)
    except ValueError:
        idx = 0
    return palette[idx % len(palette)]
