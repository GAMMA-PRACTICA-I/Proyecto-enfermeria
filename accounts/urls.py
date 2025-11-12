# accounts/urls.py
from django.urls import path
from django.views.generic.base import RedirectView
from .views import register
from .views import (
    landing_por_rol,            # <— NUEVO: despachador por rol
    dashboard_estudiante,
    FichaView,
    ReviewDashboardView,
    ReviewDocumentUpdateView,
    ApproveFichaView,
    ObserveFichaView,
    ficha_pdf,
    obtener_comentarios,
)
from . import views

urlpatterns = [
    
    path("register/", register, name="register"),

    # Mantengo tu redirect de login
    path("login/", RedirectView.as_view(url="/accounts/login/", permanent=False)),
    
    path("revisar/ficha/<int:ficha_id>/comentarios/", obtener_comentarios, name="obtener_comentarios"),
    path("revisar/ficha/<int:ficha_id>/observar/", ObserveFichaView.as_view(), name="observar_ficha"),
    
    path("revisor/ficha/<int:ficha_id>/", views.detalle_ficha_revisor, name="detalle_ficha_revisor"),

    # Raíz: decide según rol (REVIEWER -> revisiones; otros -> estudiante)
    path("", landing_por_rol, name="landing_por_rol"),

    # Acceso directo al dashboard de estudiante (opcional, por si lo referencian)
    path("estudiante/", dashboard_estudiante, name="dashboard_estudiante"),

    # Flujo de ficha
    path("ficha/", FichaView.as_view(), name="ficha"),
    path("ficha/pdf/", ficha_pdf, name="ficha_pdf"),

    # Panel revisor y acciones
    path("revisiones/pendientes/", ReviewDashboardView.as_view(), name="revisiones_pendientes"),
    path("revisar/documento/<int:doc_id>/", ReviewDocumentUpdateView.as_view(), name="revisar_documento"),
    path("revisar/ficha/<int:ficha_id>/aprobar/", ApproveFichaView.as_view(), name="aprobar_ficha"),
    
    # Comentario
    path("documento/<int:id>/", views.detalle_documento, name="detalle_documento"),

]
