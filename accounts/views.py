from __future__ import annotations

import base64
import hashlib
import logging
from datetime import datetime, timedelta
from io import BytesIO
from typing import List, Tuple, Optional

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db import transaction
from django.http import (
    FileResponse,
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    JsonResponse,
    
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.text import slugify
from django.views import View

from .utils.review_email import send_revision_result_email

# === MODELOS ===
from .models import (
    User,
    StudentFicha,
    StudentGeneral,
    StudentAcademic,
    StudentMedicalBackground,
    VaccineDose,
    SerologyResult,
    VaccineType,
    SerologyResultType,
    StudentDocuments,
    StudentDocumentBlob,
    DocumentSection,
    DocumentItem,
    DocumentReviewStatus,
    DocumentReviewLog,
    StudentDeclaration,
    StudentGeneralPhotoBlob,
    StudentFieldReview,
    SupportTicket,
)

# === FORMULARIOS ===
from .forms import (
    ComentarioDocumentoForm,
    ComentarioFichaForm,
    StudentGeneralForm,
    StudentAcademicForm,
    StudentMedicalForm,
    StudentVaccinesForm,
    StudentDeclarationForm,
)

from accounts.serializers import FichaDTO
from .utils import pdf as pdf_utils
from .utils.review_map import build_prev_map


SECTION_ORDER = [
    "Certificado de Alumno Regular",
    "Carnet - Anverso",
    "Carnet - Reverso",
    "Foto Personal",
    "Antecedentes Generales",
    "Antecedentes Académicos",
    "Antecedentes Mórbidos",
    "Vacunas / Serología",
    "Documentación Adjunta",
    "Declaración",
]
ORDER_IDX = {name: i for i, name in enumerate(SECTION_ORDER)}

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG, format='[%(levelname)s accounts.views:%(lineno)d] %(message)s')


def _get_or_create_active_ficha(user: User) -> StudentFicha:
    ficha, _ = StudentFicha.objects.get_or_create(
        user=user,
        is_activa=True,
        defaults={"estado_global": StudentFicha.Estado.DRAFT},
    )
    return ficha


def _parse_date_safe(s: Optional[str]) -> Optional[datetime.date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _clean_dates_list(raw_list: List[str]) -> List[datetime.date]:
    ans: List[datetime.date] = []
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
    file_obj,
) -> StudentDocuments:
    sha, size, data = _compute_sha256(file_obj)

    section_title = dict(DocumentSection.choices).get(section, str(section))
    base = f"{section_title}__uid{ficha.user_id}__fid{ficha.id}"

    content_type = (getattr(file_obj, "content_type", "") or "").lower()
    if content_type == "application/pdf":
        ext = ".pdf"
    else:
        orig = getattr(file_obj, "name", "") or ""
        ext = "." + orig.rsplit(".", 1)[-1].lower() if "." in orig else ".bin"

    canon_name = f"{slugify(base)}{ext}"
    file_obj.name = canon_name

    doc = StudentDocuments.objects.create(
        ficha=ficha,
        section=section,
        item=item,
        file_name=canon_name,
        file_mime=content_type or None,
        review_status=DocumentReviewStatus.ADJUNTADO,
        order=0,
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
        item__in=[DocumentItem.CI_FRENTE, DocumentItem.CI_REVERSO],
    ).count()
    if count_ci > 2:
        raise ValueError("Existen más de dos adjuntos de CI (frente/reverso) para esta ficha.")


def _delete_existing_docs(ficha: StudentFicha, items: List[str]) -> None:
    qs = StudentDocuments.objects.filter(ficha=ficha, item__in=items).select_related("blob")
    for d in qs:
        try:
            if d.file and d.file.name:
                d.file.storage.delete(d.file.name)
        except Exception:
            pass
        d.delete()


@method_decorator(login_required, name="dispatch")
class UpdateUserNameAPI(View):
    """
    API para que un REVIEWER o ADMIN pueda insertar/actualizar el nombre, apellido y ROL
    a una cuenta de usuario usando el correo como identificador.
    """

    def post(self, request: HttpRequest) -> HttpResponse:
        if request.user.rol not in ["REVIEWER", "ADMIN"]:
            return JsonResponse({"ok": False, "error": "No autorizado. Rol insuficiente."}, status=403)

        email = (request.POST.get("email") or "").strip()
        first_name = (request.POST.get("first_name") or "").strip()
        last_name = (request.POST.get("last_name") or "").strip()
        rol = (request.POST.get("rol") or "").strip() # <-- NUEVO: Capturar el rol

        if not email or (not first_name and not last_name and not rol):
            return JsonResponse({"ok": False, "error": "Faltan email y/o campos para actualizar."}, status=400)

        try:
            UserModel = get_user_model()
            user_to_update = UserModel.objects.get(email__iexact=email)
        except UserModel.DoesNotExist:  # type: ignore[attr-defined]
            return JsonResponse({"ok": False, "error": f"Usuario con email '{email}' no encontrado."}, status=404)

        fields_to_update: List[str] = []
        
        # Validación y actualización de Rol
        VALID_ROLES = ["STUDENT", "REVIEWER", "ADMIN"] 
        if rol and rol in VALID_ROLES and user_to_update.rol != rol:
            user_to_update.rol = rol
            fields_to_update.append("rol")
            
        if first_name:
            user_to_update.first_name = first_name
            fields_to_update.append("first_name")
        if last_name:
            user_to_update.last_name = last_name
            fields_to_update.append("last_name")

        try:
            if fields_to_update:
                user_to_update.save(update_fields=fields_to_update)
        except Exception as e:
            return JsonResponse({"ok": False, "error": f"Error al guardar: {e}"}, status=500)

        return JsonResponse(
            {
                "ok": True,
                "message": f"Datos actualizados para el correo {email}. Campos: {', '.join(fields_to_update)}.",
                "new_name": user_to_update.get_full_name(),
                "new_rol": user_to_update.rol,
            }
        )

@login_required
def serve_ficha_photo(request: HttpRequest, ficha_id: int) -> HttpResponse:
    """Sirve la foto de perfil."""
    ficha = get_object_or_404(StudentFicha, pk=ficha_id)
    if request.user.rol != "REVIEWER" and request.user != ficha.user: return HttpResponseForbidden()
    g = getattr(ficha, "generales", None)
    if not g: return HttpResponseNotFound()
    pb = getattr(g, "photo_blob", None)
    if pb and pb.data: return HttpResponse(bytes(pb.data), content_type="image/png")
    return HttpResponseNotFound()

@login_required
def serve_document_file(request: HttpRequest, doc_id: int) -> HttpResponse:
    doc = get_object_or_404(StudentDocuments, pk=doc_id)
    if request.user.rol != "REVIEWER" and request.user != doc.ficha.user:
        return HttpResponseForbidden()
    
    if doc.blob and doc.blob.data:
        import mimetypes
        mime = doc.file_mime or mimetypes.guess_type(doc.file_name)[0] or "application/octet-stream"
        return HttpResponse(bytes(doc.blob.data), content_type=mime)
    return HttpResponseBadRequest("Sin datos")

class FichaView(View):
    template_name = "dashboards/estudiante.html"

    @method_decorator(login_required)
    def get(self, request: HttpRequest) -> HttpResponse:
        ficha = _get_or_create_active_ficha(request.user)
        is_revisor = request.user.rol == "REVIEWER"
        dto = FichaDTO.from_model(ficha).to_dict()
        rechazos = []
        if ficha.estado_global in [StudentFicha.Estado.OBSERVADA, StudentFicha.Estado.RECHAZADA]:
            rechazos = ficha.field_reviews.filter(status="REVISADO_NO_OK")
        
        return render(
            request,
            self.template_name,
            {
                "ficha": ficha,
                "ficha_json": dto,
                "is_revisor": is_revisor,
                "comentarios_ficha": ficha.comentarios_ficha.all().order_by("-fecha"),
                "form_comentario": ComentarioFichaForm(),
                "rechazos": rechazos,
            },
        )

    @method_decorator(login_required)
    @transaction.atomic
    def post(self, request: HttpRequest) -> HttpResponse:
        logger.info("POST ficha iniciado usuario=%s", request.user.email)
        user: User = request.user
        ficha, _ = StudentFicha.objects.select_for_update().get_or_create(
            user=user,
            is_activa=True,
            defaults={"estado_global": StudentFicha.Estado.DRAFT},
        )

        # I. Generales
        gen_form = StudentGeneralForm(request.POST, request.FILES)
        if gen_form.is_valid():
            g = getattr(ficha, "generales", None) or StudentGeneral(ficha=ficha)

            general_updates = {
                "nombre_legal": gen_form.cleaned_data.get("nombre_legal"),
                "genero": gen_form.cleaned_data.get("genero"),
                "rut": gen_form.cleaned_data.get("rut"),
                "fecha_nacimiento": gen_form.cleaned_data.get("fecha_nacimiento"),
                "telefono_celular": gen_form.cleaned_data.get("telefono_celular"),
                "direccion_actual": gen_form.cleaned_data.get("direccion_actual"),
                "direccion_origen": gen_form.cleaned_data.get("direccion_origen"),
                "contacto_emergencia_nombre": gen_form.cleaned_data.get("contacto_emergencia_nombre"),
                "contacto_emergencia_parentesco": gen_form.cleaned_data.get("contacto_emergencia_parentesco"),
                "contacto_emergencia_telefono": gen_form.cleaned_data.get("contacto_emergencia_telefono"),
                "centro_salud": gen_form.cleaned_data.get("centro_salud"),
                "seguro": gen_form.cleaned_data.get("prevision"),
                "seguro_detalle": gen_form.cleaned_data.get("prevision_detalle"),
            }

            fields_to_update: List[str] = []

            for field_name, value in general_updates.items():
                if value not in (None, ""):
                    setattr(g, field_name, value)
                    fields_to_update.append(field_name)

            if fields_to_update:
                g.save(update_fields=fields_to_update)
            else:
                g.save()

            foto = gen_form.cleaned_data.get("foto_ficha")
            if foto:
                sha, size, data = _compute_sha256(foto)
                pb = StudentGeneralPhotoBlob.objects.filter(general=g).first()
                if pb:
                    pb.mime = getattr(foto, "content_type", "image/png") or "image/png"
                    pb.data = data
                    pb.size_bytes = size
                    pb.sha256 = sha
                    pb.save()
                else:
                    StudentGeneralPhotoBlob.objects.create(
                        general=g,
                        mime=getattr(foto, "content_type", "image/png") or "image/png",
                        data=data,
                        size_bytes=size,
                        sha256=sha,
                    )
                g.foto_ficha.delete(save=False)
                g.foto_ficha = None
                g.save(update_fields=["foto_ficha"])

        # II. Académicos
        acad_form = StudentAcademicForm(request.POST)
        if acad_form.is_valid():
            a = getattr(ficha, "academicos", None) or StudentAcademic(ficha=ficha)

            academic_updates = {
                "nombre_social": acad_form.cleaned_data.get("nombre_social"),
                "carrera": acad_form.cleaned_data.get("carrera"),
                "anio_cursa": acad_form.cleaned_data.get("anio_cursa"),
                "estado": acad_form.cleaned_data.get("estado"),
                "asignatura": acad_form.cleaned_data.get("asignatura"),
                "correo_personal": acad_form.cleaned_data.get("correo_personal"),
            }

            fields_to_update: List[str] = []

            if gen_form.is_valid():
                correo_inst = gen_form.cleaned_data.get("correo_institucional")
                if correo_inst not in (None, ""):
                    a.correo_institucional = correo_inst
                    fields_to_update.append("correo_institucional")

            for field_name, value in academic_updates.items():
                if value not in (None, ""):
                    setattr(a, field_name, value)
                    fields_to_update.append(field_name)

            if fields_to_update:
                a.save(update_fields=fields_to_update)
            else:
                a.save()
            logger.info("Académicos guardados ficha=%s", ficha.id)
        else:
            messages.error(request, "Revise los campos de Antecedentes Académicos.")
            logger.warning("Académicos inválidos")

        # III. Mórbidos
        med_form = StudentMedicalForm(request.POST)
        if med_form.is_valid():
            m = getattr(ficha, "medicos", None) or StudentMedicalBackground(ficha=ficha)

            medical_updates = {
                "alergias_detalle": med_form.cleaned_data.get("alergias"),
                "grupo_sanguineo": med_form.cleaned_data.get("grupo_sanguineo"),
                "cronicas_detalle": med_form.cleaned_data.get("enfermedades_cronicas"),
                "medicamentos_detalle": med_form.cleaned_data.get("medicamentos_diarios"),
                "otros_antecedentes": med_form.cleaned_data.get("otros_antecedentes"),
            }

            fields_to_update = []
            for field_name, value in medical_updates.items():
                if value not in (None, ""):
                    setattr(m, field_name, value)
                    fields_to_update.append(field_name)

            if fields_to_update:
                m.save(update_fields=fields_to_update)
            else:
                m.save()
            logger.info("Mórbidos guardados ficha=%s", ficha.id)
        else:
            messages.error(request, "Revise los campos de Antecedentes Mórbidos.")
            logger.warning("Mórbidos inválidos")

        # IV. Vacunas / Serología
        vac_form = StudentVaccinesForm(request.POST)
        if vac_form.is_valid():
            ficha.vaccine_doses.all().delete()
            ficha.serologies.all().delete()

            covid_dates = _clean_dates_list(request.POST.getlist("covid_fechas[]"))
            for idx, d in enumerate(covid_dates, start=1):
                label = f"Dosis {idx}" if idx <= 3 else f"Refuerzo {idx - 3}"
                VaccineDose.objects.create(
                    ficha=ficha,
                    vaccine_type=VaccineType.COVID_19,
                    dose_label=label,
                    date=d,
                )

            hepb_dates = _clean_dates_list(request.POST.getlist("hepb_fechas[]"))
            for idx, d in enumerate(hepb_dates, start=1):
                VaccineDose.objects.create(
                    ficha=ficha,
                    vaccine_type=VaccineType.HEPATITIS_B,
                    dose_label=f"Dosis {idx}",
                    date=d,
                )

            varicela_dates = _clean_dates_list(request.POST.getlist("varicela_fechas[]"))
            for idx, d in enumerate(varicela_dates, start=1):
                VaccineDose.objects.create(
                    ficha=ficha,
                    vaccine_type=VaccineType.VARICELA,
                    dose_label=f"Dosis {idx}",
                    date=d,
                )

            var_res = (vac_form.cleaned_data.get("varicela_serologia_resultado") or "").upper()
            var_date = vac_form.cleaned_data.get("varicela_serologia_fecha")
            if var_res and var_res in SerologyResultType.values:
                SerologyResult.objects.create(
                    ficha=ficha,
                    pathogen=VaccineType.VARICELA,
                    result=var_res,
                    date=var_date or timezone.now().date(),
                )

            inf_date = vac_form.cleaned_data.get("influenza_fecha")
            if inf_date:
                VaccineDose.objects.create(
                    ficha=ficha,
                    vaccine_type=VaccineType.INFLUENZA,
                    dose_label=str(inf_date.year),
                    date=inf_date,
                )
            logger.info("Vacunas/Serología guardadas ficha=%s", ficha.id)
        else:
            messages.error(request, "Revise los campos de Vacunas/Serología.")
            logger.warning("Vacunas/Serología inválidas")

        # V. Documentos
        file_map = {
            "ci_archivos[]": (DocumentSection.GENERALES, DocumentItem.CI_FRENTE),
            "autorizacion_medica_certificados[]": (DocumentSection.MORBIDOS, DocumentItem.AUTORIZACION_MEDICA),
            "alergias_certificados[]": (DocumentSection.MORBIDOS, DocumentItem.ALERGIAS_CERT),
            "enfermedades_cronicas_certificados[]": (DocumentSection.MORBIDOS, DocumentItem.ENFERMEDADES_CERT),
            "medicamentos_diarios_certificados[]": (DocumentSection.MORBIDOS, DocumentItem.MEDICAMENTOS_CERT),
            "otros_antecedentes_certificados[]": (DocumentSection.MORBIDOS, DocumentItem.OTROS_ANTECEDENTES_CERT),
            "hepb_cert[]": (DocumentSection.VACUNAS, DocumentItem.HEPB_CERT),
            "varicela_igg[]": (DocumentSection.VACUNAS, DocumentItem.VARICELA_IGG),
            "influenza_cert[]": (DocumentSection.VACUNAS, DocumentItem.INFLUENZA_CERT),
            "sarscov2_cert[]": (DocumentSection.VACUNAS, DocumentItem.SARS_COV_2_MEVACUNO),
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

            if input_name == "ci_archivos[]":
                _delete_existing_docs(ficha, [DocumentItem.CI_FRENTE, DocumentItem.CI_REVERSO])
            else:
                _delete_existing_docs(ficha, [item])

            for idx, f in enumerate(files):
                actual_item = item
                if input_name == "ci_archivos[]":
                    actual_item = DocumentItem.CI_FRENTE if idx == 0 else DocumentItem.CI_REVERSO
                _doc_create_with_blob(ficha, section, actual_item, f)

        _save_ci_rule_guard(ficha)
        logger.info("Documentos procesados ficha=%s", ficha.id)

        # VI. Declaración
        dec_form = StudentDeclarationForm(request.POST)
        if dec_form.is_valid():
            d = getattr(ficha, "declaracion", None) or StudentDeclaration(ficha=ficha)

            declaration_updates = {
                "nombre_estudiante": dec_form.cleaned_data.get("decl_nombre"),
                "rut": dec_form.cleaned_data.get("decl_rut"),
                "fecha": dec_form.cleaned_data.get("decl_fecha"),
                "firma": dec_form.cleaned_data.get("decl_firma"),
            }

            fields_to_update = []
            for field_name, value in declaration_updates.items():
                if value not in (None, ""):
                    setattr(d, field_name, value)
                    fields_to_update.append(field_name)

            if fields_to_update:
                d.save(update_fields=fields_to_update)
            else:
                d.save()
            logger.info("Declaración guardada ficha=%s", ficha.id)
        else:
            messages.error(request, "Revise los campos de Declaración.")
            logger.warning("Declaración inválida")

        if user.rol == "STUDENT":
            finalizar = request.POST.get("finalizar")
            ficha.estado_global = (
                StudentFicha.Estado.ENVIADA if finalizar else StudentFicha.Estado.DRAFT
            )
            ficha.save()
            logger.info("Estado final de la ficha=%s estado=%s", ficha.id, ficha.estado_global)

        messages.success(request, "Ficha guardada correctamente.")

        if "comentar" in request.POST:
            form = ComentarioFichaForm(request.POST)
            if form.is_valid():
                comentario = form.save(commit=False)
                comentario.autor = request.user
                comentario.ficha = ficha
                comentario.save()
            return redirect("ficha")

        return redirect("dashboard_estudiante")


@method_decorator(login_required, name="dispatch")
class ReviewDashboardView(View):
    template_name = "dashboards/revision_pendientes.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        if request.user.rol != "REVIEWER":
            return HttpResponseForbidden("No autorizado.")
        fichas = (
            StudentFicha.objects.filter(
                estado_global__in=[
                    StudentFicha.Estado.ENVIADA,
                    StudentFicha.Estado.EN_REVISION,
                    StudentFicha.Estado.OBSERVADA,
                ]
            )
            .order_by("created_at")
        )
        return render(request, self.template_name, {"fichas": fichas})

@method_decorator(login_required, name="dispatch")
class DeleteStudentFichaAPI(View):
    """
    API para eliminar la ficha activa de un estudiante usando su correo.
    Restringida a rol REVIEWER o ADMIN.
    """

    def post(self, request: HttpRequest) -> HttpResponse:
        if request.user.rol not in ["REVIEWER", "ADMIN"]:
            return JsonResponse({"ok": False, "error": "No autorizado. Rol insuficiente."}, status=403)

        email_to_clean = (request.POST.get("email") or "").strip()

        if not email_to_clean:
            return JsonResponse({"ok": False, "error": "El campo de email no puede estar vacío."}, status=400)

        try:
            UserModel = get_user_model()
            user_to_clean = UserModel.objects.get(email__iexact=email_to_clean)
        except UserModel.DoesNotExist:
            return JsonResponse(
                {"ok": False, "error": f"Usuario con email '{email_to_clean}' no encontrado."},
                status=404,
            )

        if user_to_clean.rol != "STUDENT":
             return JsonResponse(
                {"ok": False, "error": f"El usuario {email_to_clean} no es un estudiante (rol: {user_to_clean.rol})."},
                status=400,
            )

        with transaction.atomic():
            # Buscar y eliminar fichas activas del estudiante
            ficha_qs = StudentFicha.objects.filter(user=user_to_clean, is_activa=True)
            ficha_count = ficha_qs.count()
            if ficha_count == 0:
                 return JsonResponse(
                    {"ok": False, "error": f"El estudiante {email_to_clean} no tiene una ficha activa para eliminar."},
                    status=404,
                )
            
            # La eliminación en cascada debería manejar el resto de datos asociados
            ficha_qs.delete()


        return JsonResponse(
            {"ok": True, "message": f"Ficha(s) activa(s) de {email_to_clean} eliminada(s) exitosamente ({ficha_count} ficha(s) borrada(s))."}
        )

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

        pending = ficha.documents.exclude(review_status=DocumentReviewStatus.REVISADO_OK).exists()
        if pending:
            return JsonResponse(
                {"ok": False, "error": "Aún hay documentos pendientes/no OK."},
                status=400,
            )

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

@method_decorator(login_required, name="dispatch")
class FetchUserDetailsAPI(View):
    """
    API para obtener el detalle de un usuario por email.
    Incluye RUT, rol y si tiene ficha activa.
    """
    def get(self, request: HttpRequest) -> HttpResponse:
        if request.user.rol not in ["REVIEWER", "ADMIN"]:
            return JsonResponse({"ok": False, "error": "No autorizado. Rol insuficiente."}, status=403)

        email = (request.GET.get("email") or "").strip()
        if not email:
            return JsonResponse({"ok": False, "error": "Falta el email."}, status=400)

        try:
            UserModel = get_user_model()
            user_to_fetch = UserModel.objects.get(email__iexact=email)
            
            # Verificar si tiene ficha activa
            has_active_ficha = StudentFicha.objects.filter(user=user_to_fetch, is_activa=True).exists()

            return JsonResponse(
                {
                    "ok": True,
                    "first_name": user_to_fetch.first_name,
                    "last_name": user_to_fetch.last_name,
                    "rut": getattr(user_to_fetch, "rut", "N/A"), # Asume que el campo 'rut' existe
                    "rol": user_to_fetch.rol,
                    "has_active_ficha": has_active_ficha,
                }
            )
        except UserModel.DoesNotExist:
            return JsonResponse({"ok": False, "error": f"Usuario con email '{email}' no encontrado."}, status=404)
        except Exception as e:
            logger.error("Error fetching user details: %s", e)
            return JsonResponse({"ok": False, "error": "Error interno del servidor."}, status=500)

def home(request: HttpRequest) -> HttpResponse:
    """
    Página raíz del sitio:
    - Si NO está autenticado -> lo llevo al login.
    - Si está autenticado     -> lo mando al dashboard según su rol.
    """
    if not request.user.is_authenticated:
        return redirect("login")
    return landing_por_rol(request)


def logout_to_login(request: HttpRequest) -> HttpResponse:
    logout(request)
    return redirect("login")


@login_required
def dashboard_estudiante(request: HttpRequest) -> HttpResponse:
    ficha = StudentFicha.objects.filter(user=request.user, is_activa=True).first()
    documentos = (
        StudentDocuments.objects.filter(ficha=ficha).order_by("-uploaded_at")
        if ficha
        else []
    )

    ctx = {
        "ficha": ficha,
        "documentos": documentos,
        "ficha_pdf_disponible": bool(ficha),
        "is_revisor": request.user.rol == "REVIEWER",
    }
    return render(request, "dashboards/estudiante.html", ctx)


@login_required
def soporte_estudiante(request: HttpRequest) -> HttpResponse:
    """
    Vista de soporte para el ESTUDIANTE:
    - GET  -> muestra el formulario de soporte.
    - POST -> crea un SupportTicket asociado al usuario logueado.
    """
    if request.method == "POST":
        tipo = (request.POST.get("tipo_consulta") or "").strip()
        asunto = (request.POST.get("asunto") or "").strip()
        detalle = (request.POST.get("detalle") or "").strip()

        if not asunto or not detalle:
            messages.error(request, "Debes completar el asunto y el detalle de la consulta.")
            return redirect("soporte_estudiante")

        if not tipo:
            tipo = "Otra consulta"

        SupportTicket.objects.create(
            user=request.user,
            tipo_consulta=tipo,
            asunto=asunto,
            detalle=detalle,
        )

        messages.success(request, "Tu solicitud de soporte fue enviada correctamente.")
        return redirect("soporte_estudiante")

    return render(request, "dashboards/soporte.html")


@login_required
def dashboard_admin_soporte(request: HttpRequest) -> HttpResponse:
    """
    Panel de soporte solo para usuarios con rol ADMIN.
    Muestra tickets abiertos y cerrados, y limpia los cerrados de más de 1 año.
    """
    if getattr(request.user, "rol", "") != "ADMIN":
        return HttpResponseForbidden("No autorizado.")

    hace_un_ano = timezone.now() - timedelta(days=365)
    SupportTicket.objects.filter(
        estado="CERRADA",
        updated_at__lt=hace_un_ano,
    ).delete()

    tickets_abiertos = (
        SupportTicket.objects.exclude(estado="CERRADA")
        .select_related("user")
        .order_by("-created_at")
    )
    tickets_cerrados = (
        SupportTicket.objects.filter(estado="CERRADA")
        .select_related("user")
        .order_by("-updated_at")
    )

    return render(
        request,
        "dashboards/admin.html",
        {
            "tickets_abiertos": tickets_abiertos,
            "tickets_cerrados": tickets_cerrados,
        },
    )


@login_required
def ficha_pdf(request: HttpRequest) -> HttpResponse:
    ficha_id = request.GET.get("ficha_id")

    if ficha_id and request.user.rol == "REVIEWER":
        try:
            ficha = StudentFicha.objects.get(pk=int(ficha_id))
        except (ValueError, StudentFicha.DoesNotExist):
            return HttpResponseBadRequest("Ficha no encontrada o ID inválido.")
    else:
        ficha = StudentFicha.objects.filter(user=request.user, is_activa=True).first()
        if not ficha:
            if request.user.rol != "REVIEWER":
                return redirect("ficha")
            return HttpResponseBadRequest("No hay ficha activa para previsualizar.")

    dto = FichaDTO.from_model(ficha).to_dict()

    generales = getattr(ficha, "generales", None)
    foto_path = foto_url = foto_b64 = None

    if generales:
        if getattr(generales, "photo_blob", None) and generales.photo_blob.data:
            try:
                foto_b64 = base64.b64encode(bytes(generales.photo_blob.data)).decode("ascii")
            except Exception:
                foto_b64 = None
        elif generales.foto_ficha:
            try:
                foto_path = f"file://{generales.foto_ficha.path}"
            except Exception:
                foto_path = None
            try:
                foto_url = request.build_absolute_uri(generales.foto_ficha.url)
            except Exception:
                foto_url = None
            try:
                with generales.foto_ficha.open("rb") as f:
                    foto_b64 = base64.b64encode(f.read()).decode("ascii")
            except Exception:
                pass

    dto.setdefault("generales", {})
    dto["generales"]["foto_ficha_path"] = foto_path
    dto["generales"]["foto_ficha_url"] = foto_url
    dto["generales"]["foto_ficha_b64"] = foto_b64

    base_pdf = pdf_utils.render_html_to_pdf_bytes(
        "pdf/ficha_pdf.html",
        {
            "ficha": ficha,
            "data": dto,
            "comentarios": ficha.comentarios_ficha.all().order_by("-fecha"),
        },
    )

    streams: List[bytes] = [base_pdf]
    docs_qs = ficha.documents.select_related("blob").order_by("uploaded_at", "id")

    for doc in docs_qs:
        raw = None
        if getattr(doc, "blob", None) and doc.blob.data:
            raw = bytes(doc.blob.data)
        elif doc.file:
            try:
                raw = doc.file.read()
            except Exception:
                raw = None
        if not raw:
            continue

        mime = (doc.file_mime or getattr(doc.file, "content_type", "") or "").lower()
        is_pdf, is_img = pdf_utils.classify_attachment(doc.file_name or "", mime)

        title = f"{doc.section} — {doc.item}" if doc.section and doc.item else "Documento adjunto"
        subtitle = f"Alumno: {ficha.user.email}  |  Ficha #{ficha.id}"
        if doc.file_name:
            subtitle += f"  | archivo: {doc.file_name}"

        streams.append(pdf_utils.title_page_pdf_bytes(title, subtitle))

        if is_pdf:
            streams.append(raw)
        elif is_img:
            streams.append(pdf_utils.image_bytes_to_singlepage_pdf_bytes(raw, mime=mime or "image/png"))

    merged = pdf_utils.merge_pdf_streams(streams)
    return FileResponse(BytesIO(merged), content_type="application/pdf", filename=f"ficha_{ficha.id}.pdf")


@login_required
def delete_account_tool_view(request: HttpRequest) -> HttpResponse:
    """
    Renderiza la herramienta de eliminación de cuentas.
    Solo accesible para Revisores y Administradores.
    """
    if request.user.rol not in ["REVIEWER", "ADMIN"]:
        return HttpResponseForbidden("No autorizado. Esta herramienta es solo para Revisores o Administradores.")
    return render(request, "accounts/delete_account_tool.html")


@method_decorator(login_required, name="dispatch")
class DeleteUserAPI(View):
    """
    API para eliminar una cuenta de usuario usando el correo.
    Restringida a rol REVIEWER o ADMIN.
    """

    def post(self, request: HttpRequest) -> HttpResponse:
        if request.user.rol not in ["REVIEWER", "ADMIN"]:
            return JsonResponse({"ok": False, "error": "No autorizado. Rol insuficiente."}, status=403)

        email_to_delete = (request.POST.get("email") or "").strip()

        if not email_to_delete:
            return JsonResponse({"ok": False, "error": "El campo de email no puede estar vacío."}, status=400)

        try:
            UserModel = get_user_model()
            user_to_delete = UserModel.objects.get(email__iexact=email_to_delete)
        except UserModel.DoesNotExist:  # type: ignore[attr-defined]
            return JsonResponse(
                {"ok": False, "error": f"Usuario con email '{email_to_delete}' no encontrado."},
                status=404,
            )

        if user_to_delete.pk == request.user.pk:
            return JsonResponse(
                {"ok": False, "error": "No puedes eliminar tu propia cuenta."},
                status=400,
            )

        user_to_delete.delete()

        return JsonResponse(
            {"ok": True, "message": f"Cuenta y datos asociados de {email_to_delete} eliminados exitosamente."}
        )


@login_required
def update_name_tool_view(request: HttpRequest) -> HttpResponse:
    """
    Renderiza la herramienta de actualización de nombre para el revisor/admin.
    """
    if request.user.rol not in ["REVIEWER", "ADMIN"]:
        return HttpResponseForbidden("No autorizado. Esta herramienta es solo para Revisores o Administradores.")
    return render(request, "accounts/update_name_tool.html")


def register(request: HttpRequest) -> HttpResponse:
    UserModel = get_user_model()

    if request.method == "POST":
        email = request.POST.get("email")
        rol = request.POST.get("rol")
        first_name = request.POST.get("first_name")
        last_name = request.POST.get("last_name")
        rut = request.POST.get("rut")
        password1 = request.POST.get("password1")
        password2 = request.POST.get("password2")

        if password1 != password2:
            messages.error(request, "Las contraseñas no coinciden.")
            return redirect("register")

        if not first_name or not last_name:
            messages.error(request, "El nombre de pila y el apellido son obligatorios.")
            return redirect("register")

        try:
            UserModel.objects.create_user(
                email=email,
                password=password1,
                rol=rol,
                first_name=first_name,
                last_name=last_name,
                rut=rut,
            )
            messages.success(request, "Usuario creado correctamente.")
            return redirect("login")
        except Exception as e:
            messages.error(request, f"Error al crear usuario: {e}")
            return redirect("register")

    return render(request, "accounts/register.html")


@login_required
def detalle_documento(request: HttpRequest, id: int) -> HttpResponse:
    documento = get_object_or_404(StudentDocuments, id=id)
    comentarios = documento.comentarios.all().order_by("-fecha")

    puede_comentar = request.user.rol in ["REVISOR", "DOCENTE"]

    if request.method == "POST" and puede_comentar:
        form = ComentarioDocumentoForm(request.POST)
        if form.is_valid():
            comentario = form.save(commit=False)
            comentario.autor = request.user
            comentario.documento = documento
            comentario.save()
            return redirect("detalle_documento", id=id)
    else:
        form = ComentarioDocumentoForm()

    return render(
        request,
        "accounts/detalle_documento.html",
        {
            "documento": documento,
            "comentarios": comentarios,
            "form": form,
            "puede_comentar": puede_comentar,
        },
    )


@login_required
def landing_por_rol(request: HttpRequest) -> HttpResponse:
    rol = getattr(request.user, "rol", "")

    if rol == "ADMIN":
        return redirect("dashboard_admin_soporte")

    if rol == "REVIEWER":
        return redirect("revisiones_pendientes")

    return redirect("dashboard_estudiante")


@method_decorator(login_required, name="dispatch")
class ReviewerFichaDetailView(View):
    template_name = "accounts/revisor_ficha.html"

    def get(self, request: HttpRequest, ficha_id: int) -> HttpResponse:
        if request.user.rol != "REVIEWER": return HttpResponseForbidden("No autorizado.")
        
        ficha = get_object_or_404(StudentFicha.objects.select_related("user", "generales", "academicos", "medicos", "declaracion"), pk=ficha_id)
        
        # Helpers
        def V(x): return x if x else "-"
        def Vdate(d): return d.strftime("%d/%m/%Y") if d else "-"
        
        g, a, m, d = getattr(ficha, "generales", None), getattr(ficha, "academicos", None), getattr(ficha, "medicos", None), getattr(ficha, "declaracion", None)
        all_docs = {doc.item: doc for doc in ficha.documents.select_related('blob').all()}
        
        # Foto Perfil
        foto_blob = getattr(g, "photo_blob", None)
        tiene_foto = bool(foto_blob and foto_blob.data)

        # 1. GENERALES (Con Correo Institucional agregado aquí)
        rows_gen = [
            ("Foto Personal", "Foto de perfil", None, "Foto Personal", True),
            ("Certificado Alumno Regular", "Documento adjunto", all_docs.get(DocumentItem.CERT_ALUMNO_REGULAR), DocumentItem.CERT_ALUMNO_REGULAR, False),
            ("Nombre legal", V(getattr(g, "nombre_legal", "")), None, "nombre_legal", False),
            ("RUT", V(getattr(g, "rut", "")), None, "rut", False),
            ("Género", V(getattr(g, "genero", "")), None, "genero", False),
            ("Fecha Nacimiento", Vdate(getattr(g, "fecha_nacimiento", None)), None, "fecha_nacimiento", False),
            ("Teléfono", V(getattr(g, "telefono_celular", "")), None, "telefono_celular", False),
            ("Correo Institucional", V(getattr(a, "correo_institucional", "")), None, "correo_institucional", False), # <-- AGREGADO
            ("Dirección Actual", V(getattr(g, "direccion_actual", "")), None, "direccion_actual", False),
            ("Dirección Origen", V(getattr(g, "direccion_origen", "")), None, "direccion_origen", False),
            ("Contacto Emergencia", V(getattr(g, "contacto_emergencia_nombre", "")), None, "contacto_emergencia_nombre", False),
            ("Teléfono Emergencia", V(getattr(g, "contacto_emergencia_telefono", "")), None, "contacto_emergencia_telefono", False),
            ("Parentesco", V(getattr(g, "contacto_emergencia_parentesco", "")), None, "contacto_emergencia_parentesco", False),
            ("Centro Salud", V(getattr(g, "centro_salud", "")), None, "centro_salud", False),
            ("Previsión", f"{V(getattr(g, 'seguro', ''))} {V(getattr(g, 'seguro_detalle', ''))}", None, "seguro", False),
        ]

        # 2. ACADÉMICOS (Sin Correo Institucional)
        rows_acad = [
            ("Nombre Social", V(getattr(a, "nombre_social", "")), None, "nombre_social", False),
            ("Carrera", V(getattr(a, "carrera", "")), None, "carrera", False),
            ("Año", V(getattr(a, "anio_cursa", "")), None, "anio_cursa", False),
            ("Estado", V(getattr(a, "estado", "")), None, "estado", False),
            ("Asignatura", V(getattr(a, "asignatura", "")), None, "asignatura", False),
            ("Correo Personal", V(getattr(a, "correo_personal", "")), None, "correo_personal", False),
        ]

        # 3. MÓRBIDOS (Grupo sanguíneo al inicio)
        rows_morb = [
            ("Grupo Sanguíneo", V(getattr(m, "grupo_sanguineo", "")), None, "grupo_sanguineo", False),
            ("Alergias", V(getattr(m, "alergias_detalle", "")), all_docs.get(DocumentItem.ALERGIAS_CERT), "alergias_detalle", False),
            ("Enf. Crónicas", V(getattr(m, "cronicas_detalle", "")), all_docs.get(DocumentItem.ENFERMEDADES_CERT), "cronicas_detalle", False),
            ("Medicamentos", V(getattr(m, "medicamentos_detalle", "")), all_docs.get(DocumentItem.MEDICAMENTOS_CERT), "medicamentos_detalle", False),
            ("Otros", V(getattr(m, "otros_antecedentes", "")), all_docs.get(DocumentItem.OTROS_ANTECEDENTES_CERT), "otros_antecedentes", False),
        ]

        # 4. VACUNAS (Recuperadas)
        rows_vac = []
        if ficha.vaccine_doses.exists():
            for x in ficha.vaccine_doses.all().order_by('date'):
                rows_vac.append((f"{x.get_vaccine_type_display()} - {x.dose_label}", Vdate(x.date), None, f"vac_{x.id}", False))
        
        if ficha.serologies.exists():
            for s in ficha.serologies.all().order_by('date'):
                rows_vac.append((f"Serología {s.get_pathogen_display()}", f"{s.get_result_display()} ({Vdate(s.date)})", None, f"sero_{s.id}", False))
        
        if not rows_vac: rows_vac.append(("Vacunas", "No registradas", None, "vac_empty", False))

        # 5. ADJUNTOS (Cédula renombrada y ordenada)
        exclude = [DocumentItem.CERT_ALUMNO_REGULAR, DocumentItem.ALERGIAS_CERT, DocumentItem.ENFERMEDADES_CERT, DocumentItem.MEDICAMENTOS_CERT, DocumentItem.OTROS_ANTECEDENTES_CERT]
        rows_adj = []
        
        # Cédulas primero con nombre personalizado
        if DocumentItem.CI_FRENTE in all_docs:
             rows_adj.append( ("Cédula de Identidad (Frente)", "Cargado", all_docs[DocumentItem.CI_FRENTE], DocumentItem.CI_FRENTE, False) )
        if DocumentItem.CI_REVERSO in all_docs:
             rows_adj.append( ("Cédula de Identidad (Reverso)", "Cargado", all_docs[DocumentItem.CI_REVERSO], DocumentItem.CI_REVERSO, False) )

        # Resto de documentos
        for item, doc in all_docs.items():
            if item not in exclude and item not in [DocumentItem.CI_FRENTE, DocumentItem.CI_REVERSO]:
                rows_adj.append((doc.get_item_display(), "Cargado", doc, doc.item, False))
        
        if not rows_adj: rows_adj.append(("Adjuntos", "Sin documentos extra", None, "doc_empty", False))

        # 6. DECLARACIÓN (Recuperada)
        rows_decl = []
        if d: rows_decl = [("Nombre", V(d.nombre_estudiante), None, "decl_nom", False), ("RUT", V(d.rut), None, "decl_rut", False), ("Fecha", Vdate(d.fecha), None, "decl_fecha", False), ("Firma", V(d.firma), None, "decl_firma", False)]
        else: rows_decl.append(("Estado", "No firmada", None, "decl_no", False))

        # EMPAQUETADO FINAL (IMPORTANTE: Usamos render_data)
        render_data = [
            {"title": "1. Antecedentes Generales", "rows": rows_gen},
            {"title": "2. Antecedentes Académicos", "rows": rows_acad},
            {"title": "3. Antecedentes Mórbidos", "rows": rows_morb},
            {"title": "4. Vacunas / Serología", "rows": rows_vac},
            {"title": "5. Documentación Adjunta", "rows": rows_adj},
            {"title": "6. Declaración", "rows": rows_decl},
        ]

        return render(request, self.template_name, {"ficha": ficha, "render_data": render_data, "prev": build_prev_map(ficha), "tiene_foto": tiene_foto})

@method_decorator(login_required, name="dispatch")
class FieldReviewAPI(View):
    def post(self, request: HttpRequest, ficha_id: int) -> HttpResponse:
        if request.user.rol != "REVIEWER":
            return HttpResponseForbidden("No autorizado.")
        ficha = get_object_or_404(StudentFicha, pk=ficha_id)

        section = (request.POST.get("section") or "").strip()
        field_key = (request.POST.get("field_key") or "").strip()
        status = (request.POST.get("status") or "").strip()
        notes = (request.POST.get("notes") or "").strip()

        if not section or not field_key or status not in ("REVISADO_OK", "REVISADO_NO_OK"):
            return HttpResponseBadRequest("Datos incompletos.")

        obj, _ = StudentFieldReview.objects.update_or_create(
            ficha=ficha,
            field_key=field_key,
            defaults={
                "section": section,
                "status": status,
                "notes": notes if status == "REVISADO_NO_OK" else "",
                "reviewed_by": request.user,
                "reviewed_at": timezone.now(),
            },
        )
        return JsonResponse({"ok": True, "status": obj.status})

@method_decorator(login_required, name="dispatch")
class FinalizeReviewAPI(View):
    def post(self, request: HttpRequest, ficha_id: int) -> HttpResponse:
        if request.user.rol != "REVIEWER":
            return HttpResponseForbidden("No autorizado.")
        
        ficha = get_object_or_404(StudentFicha, pk=ficha_id)

        # === CORRECCIÓN DE FANTASMAS ===
        # Borramos explícitamente los registros viejos que causan conflicto.
        # El sistema actual usa claves como 'medicamentos_detalle', pero la BD tiene 'Medicamentos diarios'.
        # Al borrar los viejos, el sistema solo evaluará lo que ves en pantalla.
        fantasmas = [
            "Medicamentos diarios", 
            "Otros antecedentes", 
            "Enfermedades crónicas", 
            "Alergias", 
            "Alergias (detalle)",
            "Crónicas (detalle)"
        ]
        ficha.field_reviews.filter(field_key__in=fantasmas).delete()
        # ================================

        # Ahora sí, buscamos si queda algo rojo real
        qs_rejected = ficha.field_reviews.filter(status="REVISADO_NO_OK")
        exists_no_ok = qs_rejected.exists()

        global_notes = (request.POST.get("global_notes") or "").strip()
        rechazados: List[dict] = []
        combined_notes = None

        if exists_no_ok:
            # RECHAZADA
            ficha.estado_global = StudentFicha.Estado.RECHAZADA
            rechazados = list(qs_rejected.values("section", "field_key", "notes"))
            
            detalles: List[str] = []
            for r in rechazados:
                linea = f"- {r['section']} • {r['field_key']}"
                if r.get("notes"):
                    linea += f": {r['notes']}"
                detalles.append(linea)

            if global_notes:
                detalles.append("")
                detalles.append(f"Comentario general: {global_notes}")

            combined_notes = "\n".join(detalles)
            
        else:
            # APROBADA
            ficha.estado_global = StudentFicha.Estado.APROBADA
            combined_notes = global_notes if global_notes else None

        # Guardar cambios
        ficha.observaciones_globales = combined_notes
        ficha.revisado_por = request.user
        ficha.revisado_en = timezone.now()
        
        ficha.save(update_fields=[
            "estado_global", 
            "observaciones_globales", 
            "revisado_por", 
            "revisado_en", 
            "updated_at"
        ])

        # Enviar correo
        base_url = request.build_absolute_uri(reverse("dashboard_estudiante"))
        try:
            send_revision_result_email(
                ficha=ficha,
                rechazados=rechazados,
                global_notes=global_notes,
                aprobado=not exists_no_ok,
                base_url=base_url,
            )
        except Exception as e:
            logger.error(f"Error email ficha {ficha.id}: {e}")

        return JsonResponse({
            "ok": True, 
            "estado": ficha.estado_global,
            "culpables": [f"{r['section']} -> {r['field_key']}" for r in rechazados]
        })

@login_required
def supportticket_detail_api(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Devuelve el detalle de un ticket de soporte en JSON.
    Solo ADMIN, llamada por AJAX (XHR).
    """
    if getattr(request.user, "rol", "") != "ADMIN":
        return HttpResponseForbidden("No autorizado.")

    if request.method != "GET" or request.headers.get("X-Requested-With") != "XMLHttpRequest":
        raise Http404()

    ticket = get_object_or_404(SupportTicket.objects.select_related("user"), pk=pk)

    return JsonResponse(
        {
            "id": ticket.pk,
            "tipo_consulta": ticket.tipo_consulta,
            "asunto": ticket.asunto,
            "detalle": ticket.detalle,
            "estado": ticket.estado,
            "student_name": ticket.user.get_full_name() or ticket.user.email,
            "student_email": ticket.user.email,
            "created_at": ticket.created_at.strftime("%Y-%m-%d %H:%M"),
            "respuesta_admin": ticket.respuesta_admin or "",
        }
    )


@login_required
def supportticket_reply(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Recibe la respuesta del admin a un ticket, cierra el ticket
    y envía un correo al estudiante.
    Solo ADMIN, llamada por AJAX (XHR).
    """
    if getattr(request.user, "rol", "") != "ADMIN":
        return HttpResponseForbidden("No autorizado.")

    if request.method != "POST" or request.headers.get("X-Requested-With") != "XMLHttpRequest":
        raise Http404()

    ticket = get_object_or_404(SupportTicket.objects.select_related("user"), pk=pk)
    respuesta = (request.POST.get("respuesta") or "").strip()

    if not respuesta:
        return JsonResponse({"ok": False, "error": "La respuesta no puede estar vacía."}, status=400)

    ticket.respuesta_admin = respuesta
    ticket.estado = "CERRADA"
    ticket.responded_at = timezone.now()
    ticket.save(update_fields=["respuesta_admin", "estado", "responded_at", "updated_at"])

    if ticket.user.email:
        subject = f"[Campo Clínico UNAB] Respuesta a tu solicitud de soporte #{ticket.pk}"
        body = (
            f"Hola {ticket.user.get_full_name() or ticket.user.username},\n\n"
            f"Tu solicitud de soporte ha sido revisada.\n\n"
            f"Tema: {ticket.asunto}\n"
            f"Tipo de consulta: {ticket.tipo_consulta}\n\n"
            f"Detalle enviado por ti:\n{ticket.detalle}\n\n"
            f"Respuesta del equipo:\n{respuesta}\n\n"
            "Saludos cordiales,\n"
            "Equipo de Campo Clínico UNAB"
        )
        send_mail(
            subject,
            body,
            None,
            [ticket.user.email],
            fail_silently=True,
        )

    return JsonResponse({"ok": True, "message": "Respuesta enviada y ticket marcado como cerrado."})
