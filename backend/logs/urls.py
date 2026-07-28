from django.urls import path

from logs.views import OperateLogListView, StorageStatsView

urlpatterns = [
    path("", OperateLogListView.as_view(), name="logs-list"),
    path("stats/", StorageStatsView.as_view(), name="logs-stats"),
]
