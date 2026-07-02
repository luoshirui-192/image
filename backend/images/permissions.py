"""Image ownership helpers for server vs client roles."""
from __future__ import annotations

from images.models import ImageInfo


def is_admin(user) -> bool:
    return getattr(user, "role", "") == "admin"


def can_modify_image(user, image: ImageInfo) -> bool:
    """Admin or the original uploader may edit/delete/restore their images."""
    if is_admin(user):
        return True
    username = getattr(user, "username", "")
    return bool(username and image.upload_user == username)
