from __future__ import annotations

import hashlib
from datetime import datetime
from typing import List, Tuple, Optional

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import (
    HttpRequest, HttpResponse, JsonResponse, HttpResponseForbidden
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View

from .forms import (
    StudentGeneralForm, StudentAcademicForm, StudentMedicalForm,
    StudentVaccinesForm, StudentDeclarationForm
)
from .models import (
    User, StudentFicha, StudentGeneral, StudentAcademic, StudentMedicalBackground,
    VaccineDose, SerologyResult, VaccineType, SerologyResultType,
    StudentDocuments, StudentDocumentBlob, DocumentSection, DocumentItem,
    DocumentReviewStatus, DocumentReviewLog, StudentDeclaration
)

from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect, resolve_url
from accounts.serializers import FichaDTO


def _get_or_create_active_ficha(user: User) -> StudentFicha:
    ficha = StudentFicha.objects.filter(user=user).order_by("-created_at").first()
    if ficha is None:
        ficha = StudentFicha.objects.create(user=user)
    return ficha


def _parse_date_safe(s: Optional[str]) -> Optional[datetime.date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _clean_dates_list(raw_list: List[str]) -> List[datetime.date]:
    ans = []
    for s in raw_list:
        d = _parse_date_safe(s)
        if d:
            ans.append(d)
    return ans


def _compute_sha256(uploaded_file) -> Tuple[str, int, bytes]:
    h = hashlib.sha256()
    data = b""
    size = 0
    for chunk in uploaded_file.chunks():
        h.update(chunk)
        size += len(chunk)
        data += chunk
    return h.hexdigest(), size, data


def _doc_create_with_blob(
    ficha: StudentFicha,
    section: str,
    item: str,
    uploaded_file
) -> StudentDocuments:
    sha, size, data = _compute_sha256(uploaded_file)
    doc = StudentDocuments.objects.create(
        ficha=ficha,
        section=section,
        item=item,
        file_name=uploaded_file.name,
        file_mime=getattr(uploaded_file, "content_type", None),
        review_status=DocumentReviewStatus.ADJUNTADO,
    )
    StudentDocumentBlob.objects.create(
        document=doc,
        storage_backend=StudentDocumentBlob.Backend.DB,
        data=data,
        size_bytes=size,
        sha256=sha,
    )
    return doc


def _save_ci_rule_guard(ficha: StudentFicha):
    count_ci = StudentDocuments.objects.filter(
        ficha=ficha,
        item__in=[DocumentItem.CI_FRENTE, DocumentItem.CI_REVERSO]
    ).count()
    if count_ci > 2:
        raise ValueError("Existen más de dos adjuntos de CI (frente/reverso) para esta ficha.")


@method_decorator(login_required, name="dispatch")
class FichaView(View):
    template_name = "dashboards/index.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        ficha = _get_or_create_active_ficha(request.user)
        is_revisor = request.user.rol == "REVIEWER"
        dto = FichaDTO.from_model(ficha).to_dict()
        return render(request, self.template_name, {
            "ficha": ficha,
            "ficha_json": dto,
            "is_revisor": is_revisor,
        })

    @transaction.atomic
    def post(self, request: HttpRequest) -> HttpResponse:
        user: User = request.user
        ficha = _get_or_create_active_ficha(user)

        # I. Generales
        gen_form = StudentGeneralForm(request.POST)
        if gen_form.is_valid():
            g = getattr(ficha, "generales", None) or StudentGeneral(ficha=ficha)
            g.nombre_legal = gen_form.cleaned_data.get("nombre_legal") or None
            g.genero = gen_form.cleaned_data.get("genero") or None
            g.rut = gen_form.cleaned_data.get("rut") or None
            g.fecha_nacimiento = gen_form.cleaned_data.get("fecha_nacimiento")
            g.telefono_celular = gen_form.cleaned_data.get("telefono_celular") or None
            g.direccion_actual = gen_form.cleaned_data.get("direccion_actual") or None
            g.direccion_origen = gen_form.cleaned_data.get("direccion_origen") or None
            g.contacto_emergencia_nombre = gen_form.cleaned_data.get("contacto_emergencia_nombre") or None
            g.contacto_emergencia_parentesco = gen_form.cleaned_data.get("contacto_emergencia_parentesco") or None
            g.contacto_emergencia_telefono = gen_form.cleaned_data.get("contacto_emergencia_telefono") or None
            g.centro_salud = gen_form.cleaned_data.get("centro_salud") or None
            # mapeo de prevision -> seguro
            g.seguro = gen_form.cleaned_data.get("prevision") or None
            g.seguro_detalle = gen_form.cleaned_data.get("prevision_detalle") or None
            g.save()
        else:
            messages.error(request, "Revise los campos de Antecedentes Generales.")

        # II. Académicos
        acad_form = StudentAcademicForm(request.POST)
        if acad_form.is_valid():
            a = getattr(ficha, "academicos", None) or StudentAcademic(ficha=ficha)
            a.nombre_social = acad_form.cleaned_data.get("nombre_social") or None
            a.carrera = acad_form.cleaned_data.get("carrera") or None
            a.anio_cursa = acad_form.cleaned_data.get("anio_cursa")
            a.estado = acad_form.cleaned_data.get("estado") or None
            a.asignatura = acad_form.cleaned_data.get("asignatura") or None
            # correo institucional viene en Generales (tu HTML lo tiene ahí)
            a.correo_institucional = gen_form.cleaned_data.get("correo_institucional") if gen_form.is_valid() else None
            a.correo_personal = acad_form.cleaned_data.get("correo_personal") or None
            a.save()
        else:
            messages.error(request, "Revise los campos de Antecedentes Académicos.")

        # III. Mórbidos
        med_form = StudentMedicalForm(request.POST)
        if med_form.is_valid():
            m = getattr(ficha, "medicos", None) or StudentMedicalBackground(ficha=ficha)
            m.alergias_detalle = med_form.cleaned_data.get("alergias") or None
            m.grupo_sanguineo = med_form.cleaned_data.get("grupo_sanguineo") or None
            m.cronicas_detalle = med_form.cleaned_data.get("enfermedades_cronicas") or None
            m.medicamentos_detalle = med_form.cleaned_data.get("medicamentos_diarios") or None
            m.otros_antecedentes = med_form.cleaned_data.get("otros_antecedentes") or None
            m.save()
        else:
            messages.error(request, "Revise los campos de Antecedentes Mórbidos.")

        # IV. Vacunas / Serología
        vac_form = StudentVaccinesForm(request.POST)
        if vac_form.is_valid():
            # borrado/replace para simplificar
            ficha.vaccine_doses.all().delete()
            ficha.serologies.all().delete()

            covid_dates = _clean_dates_list(request.POST.getlist("covid_fechas[]"))
            for idx, d in enumerate(covid_dates, start=1):
                label = f"Dosis {idx}" if idx <= 3 else f"Refuerzo {idx - 3}"
                VaccineDose.objects.create(
                    ficha=ficha, vaccine_type=VaccineType.COVID_19, dose_label=label, date=d
                )

            hepb_dates = _clean_dates_list(request.POST.getlist("hepb_fechas[]"))
            for idx, d in enumerate(hepb_dates, start=1):
                VaccineDose.objects.create(
                    ficha=ficha, vaccine_type=VaccineType.HEPATITIS_B, dose_label=f"Dosis {idx}", date=d
                )

            varicela_dates = _clean_dates_list(request.POST.getlist("varicela_fechas[]"))
            for idx, d in enumerate(varicela_dates, start=1):
                VaccineDose.objects.create(
                    ficha=ficha, vaccine_type=VaccineType.VARICELA, dose_label=f"Dosis {idx}", date=d
                )

            var_res = (vac_form.cleaned_data.get("varicela_serologia_resultado") or "").upper()
            var_date = vac_form.cleaned_data.get("varicela_serologia_fecha")
            if var_res and var_res in SerologyResultType.values:
                SerologyResult.objects.create(
                    ficha=ficha, pathogen=VaccineType.VARICELA, result=var_res,
                    date=var_date or timezone.now().date()
                )

            inf_date = vac_form.cleaned_data.get("influenza_fecha")
            if inf_date:
                VaccineDose.objects.create(
                    ficha=ficha, vaccine_type=VaccineType.INFLUENZA, dose_label=str(inf_date.year), date=inf_date
                )
        else:
            messages.error(request, "Revise los campos de Vacunas/Serología.")

        # V. Documentos (adjuntos)
        # names EXACTOS del HTML: todos con [] cuando corresponde
        file_map = {
            # Identificación
            "ci_archivos[]": (DocumentSection.GENERALES, DocumentItem.CI_FRENTE),  # alternamos frente/reverso por orden

            # Autorización médica
            "autorizacion_medica_certificados[]": (DocumentSection.MORBIDOS, DocumentItem.AUTORIZACION_MEDICA),

            # Mórbidos asociados a campos
            "alergias_certificados[]": (DocumentSection.MORBIDOS, DocumentItem.ALERGIAS_CERT),
            "enfermedades_cronicas_certificados[]": (DocumentSection.MORBIDOS, DocumentItem.ENFERMEDADES_CERT),
            "medicamentos_diarios_certificados[]": (DocumentSection.MORBIDOS, DocumentItem.MEDICAMENTOS_CERT),
            "otros_antecedentes_certificados[]": (DocumentSection.MORBIDOS, DocumentItem.OTROS_ANTECEDENTES_CERT),

            # Vacunas/Serologías
            "hepb_cert[]": (DocumentSection.VACUNAS, DocumentItem.HEPB_CERT),
            "varicela_igg[]": (DocumentSection.VACUNAS, DocumentItem.VARICELA_IGG),
            "influenza_cert[]": (DocumentSection.VACUNAS, DocumentItem.INFLUENZA_CERT),
            "sarscov2_cert[]": (DocumentSection.VACUNAS, DocumentItem.SARS_COV_2_MEVACUNO),

            # Cursos (documentación adjunta)
            "curso_intro_covid_certificados[]": (DocumentSection.ADJUNTA, DocumentItem.CURSO_INTRO_COVID),
            "curso_epp_certificados[]": (DocumentSection.ADJUNTA, DocumentItem.CURSO_EPP),
            "curso_iaas_certificados[]": (DocumentSection.ADJUNTA, DocumentItem.CURSO_IAAS),
            "curso_rcp_bls_certificados[]": (DocumentSection.ADJUNTA, DocumentItem.CURSO_RCP_BLS),
            "induccion_cc_certificados[]": (DocumentSection.ADJUNTA, DocumentItem.INDUCCION_CC),
        }

        for input_name, (section, item) in file_map.items():
            files = request.FILES.getlist(input_name)
            if not files:
                continue
            for idx, f in enumerate(files):
                actual_item = item
                if input_name == "ci_archivos[]":
                    actual_item = DocumentItem.CI_FRENTE if idx == 0 else DocumentItem.CI_REVERSO
                _doc_create_with_blob(ficha, section, actual_item, f)

        _save_ci_rule_guard(ficha)

        # VI. Declaración
        dec_form = StudentDeclarationForm(request.POST)
        if dec_form.is_valid():
            d = getattr(ficha, "declaracion", None) or StudentDeclaration(ficha=ficha)
            d.nombre_estudiante = dec_form.cleaned_data.get("decl_nombre") or ""
            d.rut = dec_form.cleaned_data.get("decl_rut") or ""
            fecha_manual = dec_form.cleaned_data.get("decl_fecha")
            if fecha_manual:
                d.fecha = fecha_manual
            d.firma = dec_form.cleaned_data.get("decl_firma") or None
            d.save()
        else:
            messages.error(request, "Revise los campos de Declaración.")

        # Estado post-guardado (estudiante)
        if user.rol == "STUDENT":
            finalizar = request.POST.get("finalizar")
            ficha.estado_global = StudentFicha.Estado.ENVIADA if finalizar else StudentFicha.Estado.DRAFT
            ficha.save()

        messages.success(request, "Ficha guardada correctamente.")
        return redirect(reverse("ficha"))


@method_decorator(login_required, name="dispatch")
class ReviewDashboardView(View):
    template_name = "dashboards/revision_pendientes.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        if request.user.rol != "REVIEWER":
            return HttpResponseForbidden("No autorizado.")
        fichas = StudentFicha.objects.filter(
            estado_global__in=[
                StudentFicha.Estado.ENVIADA,
                StudentFicha.Estado.EN_REVISION,
                StudentFicha.Estado.OBSERVADA
            ]
        ).order_by("created_at")
        return render(request, self.template_name, {"fichas": fichas})


@method_decorator(login_required, name="dispatch")
class ReviewDocumentUpdateView(View):
    """
    POST: status (ADJUNTADO/REVISADO_NO_OK/REVISADO_OK), notes (opcional)
    """
    def post(self, request: HttpRequest, doc_id: int) -> HttpResponse:
        if request.user.rol != "REVIEWER":
            return HttpResponseForbidden("No autorizado.")
        doc = get_object_or_404(StudentDocuments, pk=doc_id)
        new_status = request.POST.get("status")
        notes = request.POST.get("notes", "")

        if new_status not in DocumentReviewStatus.values:
            return JsonResponse({"ok": False, "error": "Estado inválido."}, status=400)

        with transaction.atomic():
            old_status = doc.review_status
            doc.review_status = new_status
            doc.review_notes = notes or None
            doc.reviewed_by = request.user
            doc.reviewed_at = timezone.now()
            doc.save()

            DocumentReviewLog.objects.create(
                document=doc,
                old_status=old_status,
                new_status=new_status,
                notes=notes or None,
                reviewed_by=request.user,
                reviewed_at=timezone.now(),
            )

        return JsonResponse({"ok": True, "doc_id": doc.id, "new_status": new_status})


@method_decorator(login_required, name="dispatch")
class ApproveFichaView(View):
    def post(self, request: HttpRequest, ficha_id: int) -> HttpResponse:
        if request.user.rol != "REVIEWER":
            return HttpResponseForbidden("No autorizado.")
        ficha = get_object_or_404(StudentFicha, pk=ficha_id)

        # Todos los documentos deben estar REVISADO_OK
        pending = ficha.documents.exclude(review_status=DocumentReviewStatus.REVISADO_OK).exists()
        if pending:
            return JsonResponse({"ok": False, "error": "Aún hay documentos pendientes/no OK."}, status=400)

        ficha.estado_global = StudentFicha.Estado.APROBADA
        ficha.revisado_por = request.user
        ficha.revisado_en = timezone.now()
        ficha.save()
        return JsonResponse({"ok": True, "estado": ficha.estado_global})


@method_decorator(login_required, name="dispatch")
class ObserveFichaView(View):
    def post(self, request: HttpRequest, ficha_id: int) -> HttpResponse:
        if request.user.rol != "REVIEWER":
            return HttpResponseForbidden("No autorizado.")
        ficha = get_object_or_404(StudentFicha, pk=ficha_id)
        notes = request.POST.get("notes", "")
        ficha.estado_global = StudentFicha.Estado.OBSERVADA
        ficha.observaciones_globales = notes or None
        ficha.revisado_por = request.user
        ficha.revisado_en = timezone.now()
        ficha.save()
        return JsonResponse({"ok": True, "estado": ficha.estado_global})
def home(request):
    return redirect('dashboard_index')

def logout_to_login(request):
    logout(request)
    # Redirige a LOGIN_URL si está configurado (por defecto /accounts/login/)
    #return redirect(resolve_url(getattr(settings, "LOGIN_URL", "/accounts/login/")))
    return redirect('login')

@login_required
def dashboard(request):
    # Renderiza tu layout de dashboard (el que tiene el menú)
    return render(request, 'dashboard/index.html')