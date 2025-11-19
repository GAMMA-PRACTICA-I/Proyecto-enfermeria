from django.urls import path

from .views import (
    # Auth / navegación
    custom_login_view,
    home,
    landing_por_rol,
    logout_to_login,

    # Estudiante
    dashboard_estudiante,
    FichaView,
    soporte_estudiante,

    # Revisor
    ReviewDashboardView,
    ReviewerFichaDetailView,

    # Detalle documento
    detalle_documento,

    # APIs revisor
    FieldReviewAPI,
    FinalizeReviewAPI,

    # Admin soporte
    dashboard_admin_soporte,
    supportticket_detail_api,
    supportticket_reply,

    # Herramientas admin (usuarios)
    update_name_tool_view,
    delete_account_tool_view,
    UpdateUserNameAPI,
    DeleteUserAPI,

    # NUEVO: vista para registrar usuarios
    register,
)

urlpatterns = [
    # -------------------------
    # Auth / navegación
    # -------------------------
    path("login/", custom_login_view, name="login"),
    path("logout/", logout_to_login, name="logout"),

    # Landing según rol
    path("", landing_por_rol, name="landing_por_rol"),
    path("home/", home, name="home"),

    # -------------------------
    # Estudiante
    # -------------------------
    path("estudiante/", dashboard_estudiante, name="dashboard_estudiante"),
    path("ficha/", FichaView.as_view(), name="ficha"),
    path("soporte/", soporte_estudiante, name="soporte_estudiante"),

    # -------------------------
    # Revisor
    # -------------------------
    path("revisiones/", ReviewDashboardView.as_view(), name="revisiones_pendientes"),
    path("revisiones/<int:ficha_id>/", ReviewerFichaDetailView.as_view(), name="revisor_ficha"),

    # -------------------------
    # Detalle de documento
    # (coincide con tu vista actual: def detalle_documento(request, id))
    # -------------------------
    path(
        "documento/<int:id>/",
        detalle_documento,
        name="detalle_documento",
    ),

    # APIs de revisión
    path(
        "api/review/field/<int:ficha_id>/",
        FieldReviewAPI.as_view(),
        name="api_review_field",
    ),
    path(
        "api/review/finalize/<int:ficha_id>/",
        FinalizeReviewAPI.as_view(),
        name="api_review_finalize",
    ),

    # -------------------------
    # Admin soporte (mesa de ayuda)
    # -------------------------
    path("admin/soporte/", dashboard_admin_soporte, name="dashboard_admin_soporte"),
    path(
        "api/admin/ticket/<int:ticket_id>/",
        supportticket_detail_api,
        name="api_ticket_detail",
    ),
    path(
        "api/admin/ticket/<int:ticket_id>/reply/",
        supportticket_reply,
        name="api_ticket_reply",
    ),

    # -------------------------
    # Herramientas admin (gestión de usuarios)
    # -------------------------
    path(
        "revisiones/herramientas/nombre/",
        update_name_tool_view,
        name="update_name_tool",
    ),
    path(
        "revisiones/herramientas/eliminar-cuenta/",
        delete_account_tool_view,
        name="delete_account_tool",
    ),

     path(
        "api/user/update-name/",
        UpdateUserNameAPI.as_view(),
        name="api_update_user_name",
    ),
    path(
        "api/user/delete/",
        DeleteUserAPI.as_view(),
        name="api_delete_user",
    ),

    # -------------------------
    # Registro de usuarios (ADMIN)
    # -------------------------
    path(
        "admin/register/",
        register,
        name="register",
    ),
]
