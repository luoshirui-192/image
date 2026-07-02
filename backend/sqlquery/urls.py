"""SQL query routes — Step 13."""
from django.urls import path

from sqlquery.templates_views import SqlTemplateListCreateView
from sqlquery.views import SqlExecuteView, SqlValidateView

urlpatterns = [
    path("execute/", SqlExecuteView.as_view(), name="sql-execute"),
    path("validate/", SqlValidateView.as_view(), name="sql-validate"),
    path("templates/", SqlTemplateListCreateView.as_view(), name="sql-templates"),
]
