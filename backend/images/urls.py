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
from images.blob_catalog_views import (
    BlobCatalogConnectionsView,
    BlobCatalogDatabasesView,
    BlobCatalogObjectDetailView,
    BlobCatalogObjectsView,
)
from images.blob_migration_views import (
    BlobMigrationDiscoverView,
    BlobMigrationJobCancelView,
    BlobMigrationJobClearView,
    BlobMigrationJobDetailView,
    BlobMigrationJobErrorsExportView,
    BlobMigrationJobListCreateView,
    BlobMigrationJobPauseView,
    BlobMigrationJobResumeView,
    BlobMigrationJobRetryView,
    BlobMigrationMapStatsView,
    BlobMigrationRunView,
    BlobMigrationSourceDetailView,
    BlobMigrationSourceListCreateView,
    BlobMigrationSourceRebindView,
    BlobMigrationSourceSchemaCheckView,
    BlobTableViewLinkSourceView,
)
from images.blob_table_view_views import (
    BlobTableViewDetailView,
    BlobTableViewListCreateView,
    BlobTableViewPreviewSchemaView,
    BlobTableViewRowsView,
    BlobTableViewSchemaView,
)
from images.blob_sync_views import (
    BlobMigrationSourceSyncBackfillView,
    BlobMigrationSourceSyncRunView,
    BlobMigrationSourceSyncSettingsView,
    BlobMigrationSourceSyncStatusView,
    BlobSyncGlobalBackfillView,
)
from images.external_db_views import (
    BlobMigrationDatabaseListView,
    ExternalDbConnectionDetailView,
    ExternalDbConnectionListCreateView,
    ExternalDbConnectionProvisionTableViewsView,
    ExternalDbConnectionTestSavedView,
    ExternalDbConnectionTestView,
)

urlpatterns = [
    path("blob-migration/databases/", BlobMigrationDatabaseListView.as_view(), name="blob-migration-databases"),
    path("blob-migration/connections/", ExternalDbConnectionListCreateView.as_view(), name="blob-migration-connections"),
    path("blob-migration/connections/test/", ExternalDbConnectionTestView.as_view(), name="blob-migration-connections-test"),
    path("blob-migration/connections/<int:pk>/", ExternalDbConnectionDetailView.as_view(), name="blob-migration-connection-detail"),
    path("blob-migration/connections/<int:pk>/test/", ExternalDbConnectionTestSavedView.as_view(), name="blob-migration-connection-test"),
    path(
        "blob-migration/connections/<int:pk>/provision-table-views/",
        ExternalDbConnectionProvisionTableViewsView.as_view(),
        name="blob-migration-connection-provision-table-views",
    ),
    path("blob-migration/discover/", BlobMigrationDiscoverView.as_view(), name="blob-migration-discover"),
    path("blob-migration/sources/", BlobMigrationSourceListCreateView.as_view(), name="blob-migration-sources"),
    path("blob-migration/sources/<int:pk>/", BlobMigrationSourceDetailView.as_view(), name="blob-migration-source-detail"),
    path(
        "blob-migration/sources/<int:pk>/rebind/",
        BlobMigrationSourceRebindView.as_view(),
        name="blob-migration-source-rebind",
    ),
    path(
        "blob-migration/sources/<int:pk>/schema-check/",
        BlobMigrationSourceSchemaCheckView.as_view(),
        name="blob-migration-source-schema-check",
    ),
    path(
        "blob-migration/sources/<int:pk>/sync/status/",
        BlobMigrationSourceSyncStatusView.as_view(),
        name="blob-migration-source-sync-status",
    ),
    path(
        "blob-migration/sources/<int:pk>/sync/settings/",
        BlobMigrationSourceSyncSettingsView.as_view(),
        name="blob-migration-source-sync-settings",
    ),
    path(
        "blob-migration/sources/<int:pk>/sync/backfill/",
        BlobMigrationSourceSyncBackfillView.as_view(),
        name="blob-migration-source-sync-backfill",
    ),
    path(
        "blob-migration/sources/<int:pk>/sync/run/",
        BlobMigrationSourceSyncRunView.as_view(),
        name="blob-migration-source-sync-run",
    ),
    path(
        "blob-migration/sync/backfill/",
        BlobSyncGlobalBackfillView.as_view(),
        name="blob-migration-sync-backfill-global",
    ),
    path("blob-migration/run/", BlobMigrationRunView.as_view(), name="blob-migration-run"),
    path("blob-migration/map-stats/", BlobMigrationMapStatsView.as_view(), name="blob-migration-map-stats"),
    path("blob-migration/jobs/", BlobMigrationJobListCreateView.as_view(), name="blob-migration-jobs"),
    path("blob-migration/jobs/retry/", BlobMigrationJobRetryView.as_view(), name="blob-migration-jobs-retry"),
    path("blob-migration/jobs/clear/", BlobMigrationJobClearView.as_view(), name="blob-migration-jobs-clear"),
    path("blob-migration/jobs/<int:pk>/", BlobMigrationJobDetailView.as_view(), name="blob-migration-job-detail"),
    path("blob-migration/jobs/<int:pk>/cancel/", BlobMigrationJobCancelView.as_view(), name="blob-migration-job-cancel"),
    path("blob-migration/jobs/<int:pk>/pause/", BlobMigrationJobPauseView.as_view(), name="blob-migration-job-pause"),
    path("blob-migration/jobs/<int:pk>/resume/", BlobMigrationJobResumeView.as_view(), name="blob-migration-job-resume"),
    path(
        "blob-migration/jobs/<int:pk>/errors/export/",
        BlobMigrationJobErrorsExportView.as_view(),
        name="blob-migration-job-errors-export",
    ),
    path("blob-migration/table-views/preview-schema/", BlobTableViewPreviewSchemaView.as_view(), name="blob-table-view-preview-schema"),
    path("blob-migration/table-views/", BlobTableViewListCreateView.as_view(), name="blob-table-view-list"),
    path("blob-migration/table-views/<int:pk>/schema/", BlobTableViewSchemaView.as_view(), name="blob-table-view-schema"),
    path("blob-migration/table-views/<int:pk>/rows/", BlobTableViewRowsView.as_view(), name="blob-table-view-rows"),
    path("blob-migration/table-views/<int:pk>/", BlobTableViewDetailView.as_view(), name="blob-table-view-detail"),
    path(
        "blob-migration/table-views/<int:pk>/link-source/",
        BlobTableViewLinkSourceView.as_view(),
        name="blob-table-view-link-source",
    ),
    # PR4 aliases — same handlers, clearer browse naming
    path("blob-browse/preview-schema/", BlobTableViewPreviewSchemaView.as_view(), name="blob-browse-preview-schema"),
    path("blob-browse/", BlobTableViewListCreateView.as_view(), name="blob-browse-list"),
    path("blob-browse/<int:pk>/schema/", BlobTableViewSchemaView.as_view(), name="blob-browse-schema"),
    path("blob-browse/<int:pk>/rows/", BlobTableViewRowsView.as_view(), name="blob-browse-rows"),
    path("blob-browse/<int:pk>/", BlobTableViewDetailView.as_view(), name="blob-browse-detail"),
    path("blob-catalog/connections/", BlobCatalogConnectionsView.as_view(), name="blob-catalog-connections"),
    path("blob-catalog/databases/", BlobCatalogDatabasesView.as_view(), name="blob-catalog-databases"),
    path("blob-catalog/objects/", BlobCatalogObjectsView.as_view(), name="blob-catalog-objects"),
    path("blob-catalog/objects/<str:name>/", BlobCatalogObjectDetailView.as_view(), name="blob-catalog-object-detail"),
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
