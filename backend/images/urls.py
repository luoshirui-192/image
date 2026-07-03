"""Image routes — Steps 12 & 14."""
from django.urls import path

from images.crud_views import ImageDetailView, ImageRestoreView
from images.serve_views import (
    ImageAccessTokenView,
    ImageDownloadView,
    ImageFileView,
    ImageThumbView,
)
from images.views import CategoryDetailView, CategoryListCreateView, ImageUploadView
from images.blob_migration_views import (
    BlobMigrationDiscoverView,
    BlobMigrationRunView,
    BlobMigrationSourceDetailView,
    BlobMigrationSourceListCreateView,
)
from images.blob_table_view_views import (
    BlobTableViewDetailView,
    BlobTableViewListCreateView,
    BlobTableViewPreviewSchemaView,
    BlobTableViewRowsView,
    BlobTableViewSchemaView,
)
from images.external_db_views import (
    BlobMigrationDatabaseListView,
    ExternalDbConnectionDetailView,
    ExternalDbConnectionListCreateView,
    ExternalDbConnectionTestSavedView,
    ExternalDbConnectionTestView,
)

urlpatterns = [
    path("blob-migration/databases/", BlobMigrationDatabaseListView.as_view(), name="blob-migration-databases"),
    path("blob-migration/connections/", ExternalDbConnectionListCreateView.as_view(), name="blob-migration-connections"),
    path("blob-migration/connections/test/", ExternalDbConnectionTestView.as_view(), name="blob-migration-connections-test"),
    path("blob-migration/connections/<int:pk>/", ExternalDbConnectionDetailView.as_view(), name="blob-migration-connection-detail"),
    path("blob-migration/connections/<int:pk>/test/", ExternalDbConnectionTestSavedView.as_view(), name="blob-migration-connection-test"),
    path("blob-migration/discover/", BlobMigrationDiscoverView.as_view(), name="blob-migration-discover"),
    path("blob-migration/sources/", BlobMigrationSourceListCreateView.as_view(), name="blob-migration-sources"),
    path("blob-migration/sources/<int:pk>/", BlobMigrationSourceDetailView.as_view(), name="blob-migration-source-detail"),
    path("blob-migration/run/", BlobMigrationRunView.as_view(), name="blob-migration-run"),
    path("blob-migration/table-views/preview-schema/", BlobTableViewPreviewSchemaView.as_view(), name="blob-table-view-preview-schema"),
    path("blob-migration/table-views/", BlobTableViewListCreateView.as_view(), name="blob-table-view-list"),
    path("blob-migration/table-views/<int:pk>/schema/", BlobTableViewSchemaView.as_view(), name="blob-table-view-schema"),
    path("blob-migration/table-views/<int:pk>/rows/", BlobTableViewRowsView.as_view(), name="blob-table-view-rows"),
    path("blob-migration/table-views/<int:pk>/", BlobTableViewDetailView.as_view(), name="blob-table-view-detail"),
    path("upload/", ImageUploadView.as_view(), name="images-upload"),
    path("file/", ImageFileView.as_view(), name="images-file"),
    path("thumb/", ImageThumbView.as_view(), name="images-thumb"),
    path("download/", ImageDownloadView.as_view(), name="images-download"),
    path("access-token/", ImageAccessTokenView.as_view(), name="images-access-token"),
    path("categories/", CategoryListCreateView.as_view(), name="categories-list"),
    path("categories/<int:pk>/", CategoryDetailView.as_view(), name="categories-detail"),
    path("<int:pk>/restore/", ImageRestoreView.as_view(), name="images-restore"),
    path("<int:pk>/", ImageDetailView.as_view(), name="images-detail"),
]
