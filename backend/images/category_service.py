"""Default image category helpers — single category for new uploads/migrations."""
from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from images.models import ImageCategory

DEFAULT_CATEGORY_NAMES = ("默认", "默认分类")


def ensure_default_category() -> ImageCategory:
    """Return the category used for new uploads and migrations.

    Preference order:
    1. settings.DEFAULT_IMAGE_CATEGORY_ID when set and exists
    2. First row named 默认 / 默认分类 (matches legacy seed data)
    3. First row by sort/id when the table is non-empty
    4. Create 默认 when the table is empty
    """
    configured_id = getattr(settings, "DEFAULT_IMAGE_CATEGORY_ID", None)
    if configured_id:
        existing = ImageCategory.objects.filter(pk=configured_id).first()
        if existing:
            return existing

    for name in DEFAULT_CATEGORY_NAMES:
        match = ImageCategory.objects.filter(category_name=name).order_by("sort", "id").first()
        if match:
            return match

    fallback = ImageCategory.objects.order_by("sort", "id").first()
    if fallback:
        return fallback

    return ImageCategory.objects.create(
        category_name=DEFAULT_CATEGORY_NAMES[0],
        sort=0,
        create_time=timezone.now(),
    )


def resolve_category_id(category_id: int | str | None = None) -> int:
    """Resolve category_id for writes; default when omitted.

    Existing image rows keep their stored category_id — this only applies to new
    uploads, migration configs, and explicit metadata updates that pass category_id.
    """
    if category_id in (None, ""):
        return ensure_default_category().id

    try:
        parsed = int(category_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("category_id 必须为整数") from exc

    if parsed <= 0:
        raise ValueError("必须选择有效分类")

    if not ImageCategory.objects.filter(id=parsed).exists():
        raise ValueError(f"分类不存在: id={parsed}")

    return parsed
