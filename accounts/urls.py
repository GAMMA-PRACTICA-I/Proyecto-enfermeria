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
    FieldReviewAPI,
    FinalizeReviewAPI,
    UpdateUserNameAPI,
    FetchUserDetailsAPI,
    DeleteStudentFichaAPI,
    DeleteUserAPI,
    delete_account_tool_view,
    update_name_tool_view,
    soporte_estudiante,
    dashboard_admin_soporte,
    supportticket_detail_api,
    supportticket_reply,
    ficha_pdf,
    detalle_documento,
    serve_ficha_photo,
    serve_document_file,
)

urlpatterns = [
    # Raíz de /accounts/ -> decide dashboard según rol
    path("", landing_por_rol, name="landing_por_rol"),

    # Estudiante
    path("estudiante/", dashboard_estudiante, name="dashboard_estudiante"),
    path("ficha/", FichaView.as_view(), name="ficha"),
    path("ficha/pdf/", ficha_pdf, name="ficha_pdf"),

    # Revisor
    path("revisiones/", ReviewDashboardView.as_view(), name="revisiones_pendientes"),
    path("revisiones/<int:ficha_id>/", ReviewerFichaDetailView.as_view(), name="revisor_ficha",),

    # APIs revisión de documentos / ficha
    path("api/document/<int:doc_id>/review/", ReviewDocumentUpdateView.as_view(), name="api_review_document",),
    path("api/ficha/<int:ficha_id>/approve/", ApproveFichaView.as_view(), name="api_approve_ficha",),
    path("api/ficha/<int:ficha_id>/observe/", ObserveFichaView.as_view(), name="api_observe_ficha",),
    path("api/review/field/<int:ficha_id>/", FieldReviewAPI.as_view(), name="api_review_field",),
    path("api/review/finalize/<int:ficha_id>/", FinalizeReviewAPI.as_view(), name="api_review_finalize",),

    # Herramientas para ADMIN/REVIEWER (HTML)
    path("revisiones/herramientas/nombre/", update_name_tool_view, name="update_name_tool",),
    path("revisiones/herramientas/eliminar-cuenta/", delete_account_tool_view, name="delete_account_tool",),

    # APIs de administración de cuentas
    path("api/update-name/", UpdateUserNameAPI.as_view(), name="api_update_user_name",),
    path("api/delete-user/", DeleteUserAPI.as_view(), name="api_delete_user",),
    
    # APIs de administración de cuentas
    path("api/fetch-user-details/", FetchUserDetailsAPI.as_view(), name="api_fetch_user_details",),
    path("api/delete-student-ficha/", DeleteStudentFichaAPI.as_view(), name="api_delete_student_ficha",),

    # Soporte estudiante
    path("soporte/", soporte_estudiante, name="soporte_estudiante"),

    # Panel admin soporte
    path("admin/soporte/", dashboard_admin_soporte, name="dashboard_admin_soporte",),
    
    # Alias para que el template con {% url 'dashboard_admin' %} siga funcionando
    path("admin/soporte/", dashboard_admin_soporte, name="dashboard_admin",),

    # APIs de tickets de soporte
    path("api/soporte/ticket/<int:pk>/", supportticket_detail_api, name="supportticket_detail_api",),
    path("api/soporte/ticket/<int:pk>/responder/", supportticket_reply, name="supportticket_reply",),

    # Detalle de documento (comentarios)
    path("documento/<int:id>/", detalle_documento, name="detalle_documento"),
    
    path("ficha/<int:ficha_id>/photo/", serve_ficha_photo, name="serve_ficha_photo"),
    path("documento/<int:doc_id>/archivo/", serve_document_file, name="serve_document_file"),

    # Registro
    path("register/", register, name="register"),
]
