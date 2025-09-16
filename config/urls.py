from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from accounts.views import home, logout_to_login

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="accounts/login.html"), name="login"),
    path("accounts/logout/", logout_to_login, name="logout"),
    path("", home, name="home"),
]
