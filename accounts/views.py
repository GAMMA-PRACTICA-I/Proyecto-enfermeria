from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib.auth import logout


@login_required
def home(request):
    rol = getattr(request.user, "rol", "")
    if rol == "STUDENT":
        tpl = "dashboards/estudiante.html"
    elif rol == "REVIEWER":
        tpl = "dashboards/revisor.html"
    elif rol == "ADMIN":
        tpl = "dashboards/admin.html"
    else:
        tpl = "dashboards/generico.html"
    return render(request, tpl)


def logout_to_login(request):
    logout(request)
    return redirect("login")
