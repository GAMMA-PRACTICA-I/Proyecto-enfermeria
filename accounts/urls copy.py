from django.urls import path
from .views import (
    dashboard_estudiante,
    FichaView,
    ReviewDashboardView,
    ReviewDocumentUpdateView,
    ApproveFichaView,
    ObserveFichaView,
)

urlpatterns = [
    path("", dashboard_estudiante, name="dashboard_estudiante"),
    path("ficha/", FichaView.as_view(), name="ficha"),
    path("revisiones/pendientes/", ReviewDashboardView.as_view(), name="revisiones_pendientes"),
    path("revisar/documento/<int:doc_id>/", ReviewDocumentUpdateView.as_view(), name="revisar_documento"),
    path("revisar/ficha/<int:ficha_id>/aprobar/", ApproveFichaView.as_view(), name="aprobar_ficha"),
    path("revisar/ficha/<int:ficha_id>/observar/", ObserveFichaView.as_view(), name="observar_ficha"),
]
