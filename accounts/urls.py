from django.urls import path
from django.views.generic.base import RedirectView

from .views import (
    register,
    landing_por_rol,
    dashboard_estudiante,
    FichaView,
    ReviewDashboardView,
    ReviewerFichaDetailView,
    ReviewDocumentUpdateView,
    ApproveFichaView,
    ObserveFichaView,
    FieldReviewAPI,         # <- OJO: FieldReviewAPI (no ReviewFieldAPI)
    FinalizeReviewAPI,
    UpdateUserNameAPI,
    delete_account_tool_view,
    DeleteUserAPI,
    ficha_pdf,
    detalle_documento,
    update_name_tool_view,
)

urlpatterns = [
    
    # Inicio según rol
    path("", landing_por_rol, name="landing_por_rol"),
    
    #Herramientas para administrador (despues quitar permiso a revisor)
    path("revisiones/herramientas/nombre/", update_name_tool_view, name="update_name_tool"),
    path("revisiones/herramientas/eliminar-cuenta/", delete_account_tool_view, name="delete_account_tool"),
    # Auth/registro
    path("register/", register, name="register"),
    path("login/", RedirectView.as_view(url="/accounts/login/", permanent=False)),

    # Estudiante
    path("estudiante/", dashboard_estudiante, name="dashboard_estudiante"),
    path("ficha/", FichaView.as_view(), name="ficha"),
    path("ficha/pdf/", ficha_pdf, name="ficha_pdf"),

    # Panel revisor
    path("revisiones/", ReviewDashboardView.as_view(), name="revisiones_pendientes"),
    path("revisiones/<int:ficha_id>/", ReviewerFichaDetailView.as_view(), name="revisor_ficha"),

    # Acciones revisor sobre ficha/documentos
    path("revisar/documento/<int:doc_id>/", ReviewDocumentUpdateView.as_view(), name="revisar_documento"),
    path("revisar/ficha/<int:ficha_id>/aprobar/", ApproveFichaView.as_view(), name="aprobar_ficha"),
    path("revisar/ficha/<int:ficha_id>/observar/", ObserveFichaView.as_view(), name="observar_ficha"),

    # APIs que consume el JS del panel
    path("api/review/field/<int:ficha_id>/", FieldReviewAPI.as_view(), name="api_review_field"),
    path("api/review/finalize/<int:ficha_id>/", FinalizeReviewAPI.as_view(), name="api_review_finalize"),
    path("api/user/update-name/", UpdateUserNameAPI.as_view(), name="api_update_user_name"),
    path("api/user/delete/", DeleteUserAPI.as_view(), name="api_delete_user"),
    
    # Detalle de documento
    path("documento/<int:id>/", detalle_documento, name="detalle_documento"),
]
