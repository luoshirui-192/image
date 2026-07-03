"""Image query helpers."""
from __future__ import annotations

from images.models import ImageCategory


def validate_category_id(category_id: int | None) -> None:
    if category_id is None or category_id <= 0:
        raise ValueError("必须选择有效分类")
    if not ImageCategory.objects.filter(id=category_id).exists():
        raise ValueError(f"分类不存在: id={category_id}")
