from django.urls import path

from fingerprints.views import (
    FingerprintImportJobDetailView,
    FingerprintImportJobListView,
    FingerprintLayerTypeListCreateView,
    FingerprintMetaView,
    FingerprintPairCompareView,
    FingerprintPairDetailView,
    FingerprintPairImportFilesView,
    FingerprintPairImportZipView,
    FingerprintPairListView,
)

urlpatterns = [
    path("meta/", FingerprintMetaView.as_view(), name="fingerprint-meta"),
    path("layer-types/", FingerprintLayerTypeListCreateView.as_view(), name="fingerprint-layer-types"),
    path("import-jobs/", FingerprintImportJobListView.as_view(), name="fingerprint-import-jobs"),
    path("import-jobs/<int:pk>/", FingerprintImportJobDetailView.as_view(), name="fingerprint-import-job-detail"),
    path("pairs/", FingerprintPairListView.as_view(), name="fingerprint-pairs"),
    path("pairs/import/", FingerprintPairImportFilesView.as_view(), name="fingerprint-pairs-import"),
    path("pairs/import-zip/", FingerprintPairImportZipView.as_view(), name="fingerprint-pairs-import-zip"),
    path("pairs/<int:pk>/", FingerprintPairDetailView.as_view(), name="fingerprint-pair-detail"),
    path("pairs/<int:pk>/compare/", FingerprintPairCompareView.as_view(), name="fingerprint-pair-compare"),
]
