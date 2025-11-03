from django.contrib import admin 
from django.urls import path, include
from django.contrib.auth import views as auth_views
from accounts.views import home, logout_to_login
from django.conf import settings

urlpatterns = [
    path("admin/", admin.site.urls),

    # === LÍNEA NUEVA: alias para /login que usa la misma plantilla ===
    path("login/", auth_views.LoginView.as_view(template_name="accounts/login.html")),

    path("accounts/login/", auth_views.LoginView.as_view(template_name="accounts/login.html"), name="login"),
    path("accounts/logout/", logout_to_login, name="logout"),
    path("", home, name="home"),

    path(
        "accounts/password_reset/",
        auth_views.PasswordResetView.as_view(
            template_name="accounts/password_reset_form.html",
            email_template_name="accounts/password_reset_email.html",
            subject_template_name="accounts/password_reset_subject.txt",
            success_url="/accounts/password_reset/done/",
            from_email=settings.EMAIL_HOST_USER,
        ),
        name="password_reset",
    ),
    path(
        "accounts/password_reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "accounts/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url="/accounts/reset/done/",
        ),
        name="password_reset_confirm",
    ),
    path(
        "accounts/reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),

    # cambio de contraseña autenticado
    path(
        "accounts/password_change/",
        auth_views.PasswordChangeView.as_view(
            template_name="accounts/password_change_form.html",
            success_url="/accounts/password_change/done/",
        ),
        name="password_change",
    ),
    path(
        "accounts/password_change/done/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="accounts/password_change_done.html"
        ),
        name="password_change_done",
    ),

    # ====== include de las urls de la app accounts ======
    path("accounts/", include("accounts.urls")),
]
