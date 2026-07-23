from django.urls import path

from fingerprints.views import (
    FingerprintBizMetaView,
    FingerprintBizPairListView,
    FingerprintBizPairViewView,
    FingerprintBizSampleListView,
    FingerprintBizSampleViewView,
    FingerprintImportJobDetailView,
    FingerprintImportJobListView,
    FingerprintLayerTypeDetailView,
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
    path("biz/meta/", FingerprintBizMetaView.as_view(), name="fingerprint-biz-meta"),
    path("biz/pairs/", FingerprintBizPairListView.as_view(), name="fingerprint-biz-pairs"),
    path(
        "biz/pairs/<int:pk>/view/",
        FingerprintBizPairViewView.as_view(),
        name="fingerprint-biz-pair-view",
    ),
    path("biz/samples/", FingerprintBizSampleListView.as_view(), name="fingerprint-biz-samples"),
    path(
        "biz/samples/<str:cap_image_id>/view/",
        FingerprintBizSampleViewView.as_view(),
        name="fingerprint-biz-sample-view",
    ),
    path("layer-types/", FingerprintLayerTypeListCreateView.as_view(), name="fingerprint-layer-types"),
    path("layer-types/<int:pk>/", FingerprintLayerTypeDetailView.as_view(), name="fingerprint-layer-type-detail"),
    path("import-jobs/", FingerprintImportJobListView.as_view(), name="fingerprint-import-jobs"),
    path("import-jobs/<int:pk>/", FingerprintImportJobDetailView.as_view(), name="fingerprint-import-job-detail"),
    path("pairs/", FingerprintPairListView.as_view(), name="fingerprint-pairs"),
    path("pairs/import/", FingerprintPairImportFilesView.as_view(), name="fingerprint-pairs-import"),
    path("pairs/import-zip/", FingerprintPairImportZipView.as_view(), name="fingerprint-pairs-import-zip"),
    path("pairs/<int:pk>/", FingerprintPairDetailView.as_view(), name="fingerprint-pair-detail"),
    path("pairs/<int:pk>/compare/", FingerprintPairCompareView.as_view(), name="fingerprint-pair-compare"),
]
