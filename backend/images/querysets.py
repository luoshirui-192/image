"""Image list filtering and pagination — Step 15."""
from __future__ import annotations

from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.utils.dateparse import parse_datetime

from images.models import ImageCategory, ImageInfo


def _parse_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _parse_datetime(value: str | None):
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError(f"无效的时间格式: {value}")
    return parsed


def filter_image_queryset(request: HttpRequest, *, is_admin: bool = False) -> QuerySet:
    """Apply list filters from query parameters."""
    include_deleted = request.query_params.get("include_deleted") in {"1", "true", "yes"}
    username = getattr(getattr(request, "user", None), "username", "")

    qs = ImageInfo.objects.all()
    if include_deleted:
        if is_admin:
            pass
        elif username:
            qs = qs.filter(Q(is_delete=0) | Q(is_delete=1, upload_user=username))
        else:
            qs = qs.filter(is_delete=0)
    else:
        qs = qs.filter(is_delete=0)

    category_id = request.query_params.get("category_id")
    if category_id not in (None, ""):
        try:
            parsed_id = _parse_int(category_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("category_id 必须为整数") from exc
        qs = qs.filter(category_id=parsed_id)

    tags = request.query_params.get("tags", "").strip()
    if tags:
        qs = qs.filter(tags__icontains=tags)

    keyword = (request.query_params.get("keyword") or request.query_params.get("q") or "").strip()
    if keyword:
        qs = qs.filter(
            Q(image_name__icontains=keyword)
            | Q(tags__icontains=keyword)
            | Q(image_path__icontains=keyword)
            | Q(upload_user__icontains=keyword)
        )

    upload_user = request.query_params.get("upload_user", "").strip()
    if upload_user:
        qs = qs.filter(upload_user__icontains=upload_user)

    suffix = request.query_params.get("suffix", "").strip().lstrip(".")
    if suffix:
        qs = qs.filter(file_suffix__iexact=suffix)

    time_from = _parse_datetime(request.query_params.get("upload_time_from"))
    time_to = _parse_datetime(request.query_params.get("upload_time_to"))
    if time_from:
        qs = qs.filter(upload_time__gte=time_from)
    if time_to:
        qs = qs.filter(upload_time__lte=time_to)

    return qs.order_by("-upload_time", "-id")


def paginate_queryset(
    request: HttpRequest,
    queryset: QuerySet,
    *,
    default_page_size: int = 20,
    max_page_size: int = 100,
) -> dict:
    """Return paginated payload for unified API responses."""
    try:
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", default_page_size))
    except (TypeError, ValueError) as exc:
        raise ValueError("page 和 page_size 必须为整数") from exc

    if page < 1:
        raise ValueError("page 必须 >= 1")
    if page_size < 1:
        raise ValueError("page_size 必须 >= 1")

    page_size = min(page_size, max_page_size)
    total = queryset.count()
    start = (page - 1) * page_size
    end = start + page_size
    items = list(queryset[start:end])

    return {
        "count": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
        "results": items,
    }


def validate_category_id(category_id: int | None) -> None:
    if category_id is None or category_id <= 0:
        raise ValueError("必须选择有效分类")
    if not ImageCategory.objects.filter(id=category_id).exists():
        raise ValueError(f"分类不存在: id={category_id}")
