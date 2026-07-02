"""Image routes — Steps 12 & 14."""
from django.urls import path

from images.crud_views import (
    ImageBatchDeleteView,
    ImageDeletionPolicyView,
    ImageDetailView,
    ImageListView,
    ImageRestoreView,
)
from images.serve_views import (
    ImageAccessTokenView,
    ImageDownloadView,
    ImageFileView,
    ImageThumbView,
)
from images.views import CategoryDetailView, CategoryListCreateView, ImageImportView, ImageUploadView

urlpatterns = [
    path("upload/", ImageUploadView.as_view(), name="images-upload"),
    path("import/", ImageImportView.as_view(), name="images-import"),
    path("file/", ImageFileView.as_view(), name="images-file"),
    path("thumb/", ImageThumbView.as_view(), name="images-thumb"),
    path("download/", ImageDownloadView.as_view(), name="images-download"),
    path("access-token/", ImageAccessTokenView.as_view(), name="images-access-token"),
    path("batch-delete/", ImageBatchDeleteView.as_view(), name="images-batch-delete"),
    path("deletion-policy/", ImageDeletionPolicyView.as_view(), name="images-deletion-policy"),
    path("categories/", CategoryListCreateView.as_view(), name="categories-list"),
    path("categories/<int:pk>/", CategoryDetailView.as_view(), name="categories-detail"),
    path("<int:pk>/restore/", ImageRestoreView.as_view(), name="images-restore"),
    path("", ImageListView.as_view(), name="images-list"),
    path("<int:pk>/", ImageDetailView.as_view(), name="images-detail"),
]
