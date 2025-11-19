from django.contrib import messages
from django.contrib.auth import authenticate, login, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.timezone import localtime
from django.views import View
from django.db import transaction
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.timezone import localtime
from django.views import View
from django.views.decorators.http import require_GET, require_POST
from .forms import (
    ComentarioDocumentoForm,
    CustomAuthenticationForm,
    SupportTicketForm,
)
from .models import (
    ComentarioDocumento,
    FieldReview,
    StudentAcademicos,
    StudentDeclaracion,
    StudentFicha,
    StudentGenerales,
    StudentMedicos,
    StudentDocuments,
    StudentSupportTicket,
)
User = get_user_model()

@login_required
def logout_to_login(request: HttpRequest) -> HttpResponse:
    from django.contrib.auth import logout

    logout(request)
    return redirect("login")


# ---------------------------------------------------------------------------
# DASHBOARD ESTUDIANTE
# ---------------------------------------------------------------------------


class FichaView(LoginRequiredMixin, View):
    """
    Muestra la ficha del estudiante (o la ficha de otro estudiante
    si el usuario actual tiene rol de revisor).
    """

    template_name = "accounts/ficha_estudiante.html"

    def get_ficha_for_request(self, request: HttpRequest, ficha_id=None):
        """
        Devuelve la ficha en función del rol:
        - STUDENT: sólo su propia ficha
        - REVIEWER / ADMIN: puede ver fichas de otros estudiantes
        """
        user = request.user
        rol = getattr(user, "rol", "")

        if ficha_id is None:
            # Para el estudiante usamos la ficha propia
            try:
                return StudentFicha.objects.get(user=user)
            except StudentFicha.DoesNotExist:
                return None

        # Si viene ficha_id, permitimos ver otras fichas sólo a revisor/admin
        if rol not in ["REVIEWER", "ADMIN"]:
            raise Http404("No tiene permisos para ver esta ficha.")

        return get_object_or_404(StudentFicha, pk=ficha_id)

    def get(self, request: HttpRequest, ficha_id=None) -> HttpResponse:
        ficha = self.get_ficha_for_request(request, ficha_id)
        if ficha is None:
            return redirect("dashboard_estudiante")

        # Aseguramos que existan los submodelos relacionados
        generales, _ = StudentGenerales.objects.get_or_create(ficha=ficha)
        academicos, _ = StudentAcademicos.objects.get_or_create(ficha=ficha)
        medicos, _ = StudentMedicos.objects.get_or_create(ficha=ficha)
        declaracion, _ = StudentDeclaracion.objects.get_or_create(ficha=ficha)

        # Documentos
        documentos = (
            StudentDocuments.objects.filter(ficha=ficha)
            .order_by("section", "item", "uploaded_at")
        )

        # Comentarios de revisor
        comentarios = (
            ComentarioDocumento.objects.filter(ficha=ficha)
            .select_related("documento", "autor")
            .order_by("created_at")
        )

        # Para saber si el usuario actual es revisor
        is_revisor = getattr(request.user, "rol", "") == "REVIEWER"

        return render(
            request,
            self.template_name,
            {
                "ficha": ficha,
                "generales": generales,
                "academicos": academicos,
                "medicos": medicos,
                "declaracion": declaracion,
                "documentos": documentos,
                "comentarios": comentarios,
                "is_revisor": is_revisor,
            },
        )


@login_required
def dashboard_estudiante(request: HttpRequest) -> HttpResponse:
    """
    Panel de inicio del estudiante.
    """
    # Si el usuario no tiene rol de estudiante, dejamos que landing_por_rol
    # se encargue:
    if getattr(request.user, "rol", "") != "STUDENT":
        return landing_por_rol(request)

    ficha, _ = StudentFicha.objects.get_or_create(user=request.user)
    documentos = (
        StudentDocuments.objects.filter(ficha=ficha)
        .order_by("section", "item", "uploaded_at")
    )

    acciones_pendientes = []
    if not documentos.filter(section="regular", item="certificado").exists():
        acciones_pendientes.append("Subir certificado de alumno regular.")
    if not documentos.filter(section="vacunas", item="hepatitis_b").exists():
        acciones_pendientes.append("Actualizar dosis de Hepatitis B.")

    return render(
        request,
        "accounts/dashboard_estudiante.html",
        {
            "ficha": ficha,
            "documentos": documentos,
            "acciones_pendientes": acciones_pendientes,
        },
    )


@login_required
def soporte_estudiante(request: HttpRequest) -> HttpResponse:
    """
    Vista para que el estudiante envíe tickets de soporte.
    """
    ficha, _ = StudentFicha.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form = SupportTicketForm(request.POST, user=request.user)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.user = request.user
            ticket.ficha = ficha
            ticket.save()
            messages.success(
                request,
                "Tu solicitud de soporte ha sido enviada correctamente.",
            )
            return redirect("soporte_estudiante")
    else:
        form = SupportTicketForm(user=request.user)

    tickets = (
        StudentSupportTicket.objects.filter(user=request.user)
        .order_by("-created_at")
    )

    return render(
        request,
        "accounts/soporte_estudiante.html",
        {"form": form, "tickets": tickets},
    )


# ---------------------------------------------------------------------------
# LOGIN Y LANDING
# ---------------------------------------------------------------------------


def custom_login_view(request: HttpRequest) -> HttpResponse:
    """
    Login usando nuestro formulario custom, pero aprovechando AuthenticationForm
    de Django por debajo.
    """
    if request.user.is_authenticated:
        # Si ya está autenticado, lo mandamos según su rol
        return landing_por_rol(request)

    if request.method == "POST":
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return landing_por_rol(request)
    else:
        form = CustomAuthenticationForm(request)

    return render(request, "accounts/login.html", {"form": form})


@login_required
def home(request: HttpRequest) -> HttpResponse:
    """
    Entrada genérica a la aplicación. Simplemente delega en landing_por_rol
    para enviar a cada usuario a su dashboard según su rol.
    """
    return landing_por_rol(request)


@login_required
def landing_por_rol(request: HttpRequest) -> HttpResponse:
    """
    Redirección central según el rol del usuario.
    Roles esperados (en inglés):
      - ADMIN
      - REVIEWER
      - STUDENT (u otros)
    """
    rol = getattr(request.user, "rol", "")

    if rol == "ADMIN":
        # Admin users go directly to the support dashboard
        return redirect("dashboard_admin_soporte")

    if rol == "REVIEWER":
        # Reviewers go to the pending reviews board
        return redirect("revisiones_pendientes")

    # Default: student (or any other role) -> student dashboard
    return redirect("dashboard_estudiante")


# ---------------------------------------------------------------------------
# PANEL REVISOR
# ---------------------------------------------------------------------------


class ReviewDashboardView(LoginRequiredMixin, View):
    """
    Dashboard del revisor.
    """

    template_name = "accounts/dashboard_revisor.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        if getattr(request.user, "rol", "") != "REVIEWER":
            raise Http404("No tiene permisos para ver este panel.")

        fichas = (
            StudentFicha.objects.select_related("user")
            .order_by("estado_global", "user__last_name", "user__first_name")
        )

        return render(
            request,
            self.template_name,
            {"fichas": fichas},
        )


class ReviewerFichaDetailView(LoginRequiredMixin, View):
    """
    Vista de detalle de ficha para revisor.
    """

    template_name = "accounts/revisor_ficha.html"

    def get(self, request: HttpRequest, ficha_id: int) -> HttpResponse:
        if getattr(request.user, "rol", "") != "REVIEWER":
            raise Http404("No tiene permisos para ver este panel.")

        ficha = get_object_or_404(
            StudentFicha.objects.select_related(
                "generales", "academicos", "medicos", "declaracion", "user"
            ),
            pk=ficha_id,
        )

        documentos = StudentDocuments.objects.filter(ficha=ficha).order_by(
            "section", "item", "uploaded_at"
        )

        comentarios = (
            ComentarioDocumento.objects.filter(ficha=ficha)
            .select_related("documento", "autor")
            .order_by("created_at")
        )

        return render(
            request,
            self.template_name,
            {
                "ficha": ficha,
                "documentos": documentos,
                "comentarios": comentarios,
            },
        )


@login_required
def detalle_documento(
    request: HttpRequest, ficha_id: int, documento_id: int
) -> HttpResponse:
    """
    Detalle de un documento específico, con comentarios.
    """
    ficha = get_object_or_404(StudentFicha, pk=ficha_id)
    documento = get_object_or_404(StudentDocuments, pk=documento_id, ficha=ficha)

    comentarios = (
        ComentarioDocumento.objects.filter(ficha=ficha, documento=documento)
        .select_related("autor")
        .order_by("created_at")
    )

    # Reviewer and teacher roles (all role names in English)
    puede_comentar = request.user.rol in ["REVIEWER", "TEACHER"]

    if request.method == "POST":
        if not puede_comentar:
            return HttpResponseBadRequest("No tiene permisos para comentar.")
        form = ComentarioDocumentoForm(request.POST)
        if form.is_valid():
            ComentarioDocumento.objects.create(
                ficha=ficha,
                documento=documento,
                autor=request.user,
                texto=form.cleaned_data["texto"],
            )
            messages.success(request, "Comentario agregado correctamente.")
            return redirect(
                "detalle_documento", ficha_id=ficha.id, documento_id=documento.id
            )
    else:
        form = ComentarioDocumentoForm()

    return render(
        request,
        "accounts/detalle_documento.html",
        {
            "ficha": ficha,
            "documento": documento,
            "comentarios": comentarios,
            "form": form,
            "puede_comentar": puede_comentar,
        },
    )


# ---------------------------------------------------------------------------
# APIs para revisión (revisor)
# ---------------------------------------------------------------------------


class FieldReviewAPI(LoginRequiredMixin, View):
    """
    Marca un campo como observado / aprobado por el revisor.
    """

    def post(self, request: HttpRequest, ficha_id: int, field_key: str):
        if getattr(request.user, "rol", "") != "REVIEWER":
            return JsonResponse({"ok": False, "error": "No autorizado"}, status=403)

        ficha = get_object_or_404(StudentFicha, pk=ficha_id)

        status = request.POST.get("status")
        notes = request.POST.get("notes", "")

        if status not in ["OK", "OBSERVADO"]:
            return JsonResponse({"ok": False, "error": "Estado inválido"}, status=400)

        fr, _ = FieldReview.objects.get_or_create(
            ficha=ficha,
            field_key=field_key,
            defaults={"status": status, "notes": notes},
        )
        if fr.status != status or fr.notes != notes:
            fr.status = status
            fr.notes = notes
            fr.save()

        return JsonResponse({"ok": True})


class FinalizeReviewAPI(LoginRequiredMixin, View):
    """
    Finaliza la revisión de la ficha y deja un estado global.
    """

    def post(self, request: HttpRequest, ficha_id: int):
        if getattr(request.user, "rol", "") != "REVIEWER":
            return JsonResponse({"ok": False, "error": "No autorizado"}, status=403)

        ficha = get_object_or_404(StudentFicha, pk=ficha_id)
        new_status = request.POST.get("estado")

        if new_status not in ["OK", "OBSERVADA"]:
            return JsonResponse({"ok": False, "error": "Estado inválido"}, status=400)

        ficha.estado_global = new_status
        ficha.save(update_fields=["estado_global"])

        return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# PANEL ADMIN
# ---------------------------------------------------------------------------


@login_required
def dashboard_admin_soporte(request: HttpRequest) -> HttpResponse:
    """
    Panel centralizado de tickets de soporte para ADMIN.
    """
    if getattr(request.user, "rol", "") != "ADMIN":
        raise Http404("No tiene permisos para ver este panel.")

    tickets_abiertos = (
        StudentSupportTicket.objects.select_related("user")
        .filter(estado="ABIERTO")
        .order_by("created_at")
    )
    tickets_cerrados = (
        StudentSupportTicket.objects.select_related("user")
        .filter(estado="CERRADO")
        .order_by("-updated_at")
    )

    return render(
        request,
        "dashboards/admin.html",   # <-- ESTA es la ruta correcta
        {
            "tickets_abiertos": tickets_abiertos,
            "tickets_cerrados": tickets_cerrados,
        },
    )



@login_required
def supportticket_detail_api(request: HttpRequest, ticket_id: int) -> JsonResponse:
    """
    Devuelve el detalle de un ticket para el panel admin (AJAX).
    """
    if getattr(request.user, "rol", "") != "ADMIN":
        return JsonResponse({"ok": False, "error": "No autorizado"}, status=403)

    ticket = get_object_or_404(
        StudentSupportTicket.objects.select_related("user"), pk=ticket_id
    )

    data = {
        "id": ticket.id,
        "student_name": ticket.user.get_full_name() or ticket.user.username,
        "student_email": ticket.user.email,
        "tipo_consulta": ticket.tipo_consulta,
        "asunto": ticket.asunto,
        "detalle": ticket.detalle,
        "respuesta_admin": ticket.respuesta_admin or "",
        "estado": ticket.estado,
        "created_at": localtime(ticket.created_at).strftime("%Y-%m-%d %H:%M"),
    }
    return JsonResponse(data)


@login_required
def supportticket_reply(request: HttpRequest, ticket_id: int) -> JsonResponse:
    """
    Registra la respuesta del admin a un ticket y lo marca como cerrado.
    """
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Método no permitido"}, status=405)

    if getattr(request.user, "rol", "") != "ADMIN":
        return JsonResponse({"ok": False, "error": "No autorizado"}, status=403)

    ticket = get_object_or_404(StudentSupportTicket, pk=ticket_id)

    respuesta = request.POST.get("respuesta", "").strip()
    if not respuesta:
        return JsonResponse(
            {"ok": False, "error": "La respuesta no puede estar vacía."}, status=400
        )

    ticket.respuesta_admin = respuesta
    ticket.estado = "CERRADO"
    ticket.save(update_fields=["respuesta_admin", "estado", "updated_at"])

    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# UTILIDADES ADMIN (gestión de usuarios)
# ---------------------------------------------------------------------------


class UpdateUserNameAPI(LoginRequiredMixin, View):
    """
    API para que el admin actualice nombre y apellido de un usuario.
    """

    def post(self, request: HttpRequest, user_id: int):
        if getattr(request.user, "rol", "") != "ADMIN":
            return JsonResponse({"ok": False, "error": "No autorizado"}, status=403)

        user = get_object_or_404(User, pk=user_id)
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()

        if not first_name or not last_name:
            return JsonResponse(
                {"ok": False, "error": "Nombre y apellido son obligatorios."},
                status=400,
            )

        user.first_name = first_name
        user.last_name = last_name
        user.save(update_fields=["first_name", "last_name"])

        return JsonResponse({"ok": True})

@login_required
def register(request: HttpRequest) -> HttpResponse:
    """
    Formulario para que el ADMIN registre nuevos usuarios.
    El template esperado es: templates/accounts/register.html
    y desde el admin.html suele haber un link: {% url 'register' %}.
    """
    # Solo el rol ADMIN puede registrar usuarios
    if getattr(request.user, "rol", "") != "ADMIN":
        raise Http404("No tiene permisos para registrar usuarios.")

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        raw_rol = (request.POST.get("rol") or "").strip().upper()
        first_name = (request.POST.get("first_name") or "").strip()
        last_name = (request.POST.get("last_name") or "").strip()
        password1 = request.POST.get("password1") or ""
        password2 = request.POST.get("password2") or ""

        # Normalización por si en el HTML aún usas nombres antiguos
        ROLE_MAP = {
            "REVISOR": "REVIEWER",
            "DOCENTE": "TEACHER",
            "ESTUDIANTE": "STUDENT",
        }
        rol = ROLE_MAP.get(raw_rol, raw_rol)

        # Validaciones básicas
        if not email:
            messages.error(request, "El correo electrónico es obligatorio.")
            return redirect("register")

        if password1 != password2:
            messages.error(request, "Las contraseñas no coinciden.")
            return redirect("register")

        if not first_name or not last_name:
            messages.error(request, "El nombre y el apellido son obligatorios.")
            return redirect("register")

        if not rol:
            messages.error(request, "Debe seleccionar un rol para el usuario.")
            return redirect("register")

        # Verificar si ya existe un usuario con ese email
        if User.objects.filter(email__iexact=email).exists():
            messages.error(request, f"Ya existe un usuario con el email {email}.")
            return redirect("register")

        try:
            # Crear el usuario en el modelo AUTH_USER_MODEL actual
            user = User.objects.create_user(
                email=email,
                password=password1,
                rol=rol,
                first_name=first_name,
                last_name=last_name,
            )
        except Exception as e:
            messages.error(request, f"Error al crear usuario: {e}")
            return redirect("register")

        messages.success(request, f"Usuario {user.get_full_name()} creado correctamente.")
        # Tras crear el usuario, lo más lógico es volver al dashboard del admin
        return redirect("dashboard_admin_soporte")

    # GET -> mostrar formulario de registro
    return render(request, "accounts/register.html")

class DeleteUserAPI(LoginRequiredMixin, View):
    """
    API para que el admin elimine un usuario (y su ficha asociada).
    """

    def post(self, request: HttpRequest, user_id: int):
        if getattr(request.user, "rol", "") != "ADMIN":
            return JsonResponse({"ok": False, "error": "No autorizado"}, status=403)

        user = get_object_or_404(User, pk=user_id)
        with transaction.atomic():
            StudentFicha.objects.filter(user=user).delete()
            user.delete()

        return JsonResponse({"ok": True})


@login_required
def delete_account_tool_view(request: HttpRequest) -> HttpResponse:
    if getattr(request.user, "rol", "") != "ADMIN":
        raise Http404("No autorizado")
    return render(request, "accounts/admin_delete_account_tool.html")


@login_required
def update_name_tool_view(request: HttpRequest) -> HttpResponse:
    if getattr(request.user, "rol", "") != "ADMIN":
        raise Http404("No autorizado")
    return render(request, "accounts/admin_update_name_tool.html")
