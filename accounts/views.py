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

# === MODELOS ===
from .models import (
    StudentFicha, StudentDocuments, ComentarioDocumento, StudentGeneralPhotoBlob,
    User, StudentGeneral, StudentAcademic, StudentMedicalBackground,
    VaccineDose, SerologyResult, VaccineType, SerologyResultType,
    StudentDocumentBlob, DocumentSection, DocumentItem,
    DocumentReviewStatus, DocumentReviewLog, StudentDeclaration
)

# === FORMULARIOS ===
from .forms import ComentarioDocumentoForm, ComentarioFichaForm



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
from django.contrib.auth import get_user_model

#------------------------ informes pdf
from django.http import FileResponse
from io import BytesIO

# from .utils.pdf import (
#     render_html_to_pdf_bytes,
#     merge_pdf_streams,
#     image_bytes_to_singlepage_pdf_bytes,
#     classify_attachment,
#     title_page_pdf_bytes
# )
from .utils import pdf as pdf_utils

from django.utils.text import slugify

import base64


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


#-----------------------------------
import logging
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
    file_obj,                      # <-- usa file_obj como nombre del parámetro
) -> StudentDocuments:
    # hash + bytes
    sha, size, data = _compute_sha256(file_obj)

    # nombre canónico: <seccion>__uid<user>__fid<ficha>.<ext>
    section_title = dict(DocumentSection.choices).get(section, str(section))
    base = f"{section_title}__uid{ficha.user_id}__fid{ficha.id}"

    content_type = (getattr(file_obj, "content_type", "") or "").lower()
    if content_type == "application/pdf":
        ext = ".pdf"
    else:
        orig = getattr(file_obj, "name", "") or ""
        ext = "." + orig.rsplit(".", 1)[-1].lower() if "." in orig else ".bin"

    canon_name = f"{slugify(base)}{ext}"

    # asegura nombre físico y lógico
    file_obj.name = canon_name

    doc = StudentDocuments.objects.create(
        ficha=ficha,
        section=section,
        item=item,
        file_name=canon_name,                 # nombre lógico
        file_mime=content_type or None,
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


# === CAMBIO MÍNIMO: eliminar adjuntos previos del mismo item antes de crear nuevos ===
def _delete_existing_docs(ficha: StudentFicha, items: List[str]) -> None:
    """
    Borra (storage + BD) todos los adjuntos de la ficha cuyo item esté en 'items'.
    Con esto evitamos acumulación histórica y garantizamos reemplazo.
    """
    qs = StudentDocuments.objects.filter(ficha=ficha, item__in=items).select_related("blob")
    for d in qs:
        # 1) borrar archivo físico si existe en FileField
        try:
            if d.file and d.file.name:
                d.file.storage.delete(d.file.name)
        except Exception:
            pass
        # 2) borrar registro (el blob se elimina por cascade)
        d.delete()
# =============================================================================


@method_decorator(login_required, name="dispatch")
class FichaView(View):
    template_name = "dashboards/estudiante.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        ficha = _get_or_create_active_ficha(request.user)
        is_revisor = request.user.rol == "REVIEWER"
        dto = FichaDTO.from_model(ficha).to_dict()
        return render(request, self.template_name, {
            "ficha": ficha,
            "ficha_json": dto,
            "is_revisor": is_revisor,
            "comentarios_ficha": ficha.comentarios_ficha.all().order_by("-fecha"),
            "form_comentario": ComentarioFichaForm(),
        })

    @transaction.atomic
    def post(self, request: HttpRequest) -> HttpResponse:
        logging.getLogger(__name__).info(f"POST ficha iniciado usuario={request.user.email}")
        user: User = request.user
        ficha, _ = StudentFicha.objects.select_for_update().get_or_create(
            user=user,
            is_activa=True,
            defaults={"estado_global": StudentFicha.Estado.DRAFT},)

        # I. Generales
        gen_form = StudentGeneralForm(request.POST, request.FILES)
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
            g.seguro = gen_form.cleaned_data.get("prevision") or None
            g.seguro_detalle = gen_form.cleaned_data.get("prevision_detalle") or None
            g.correo_institucional = gen_form.cleaned_data.get("correo_institucional") or None

            # CLAVE: persistir 'g' antes de referenciarlo desde el blob
            g.save()

            foto = gen_form.cleaned_data.get("foto_ficha")
            if foto:
                sha, size, data = _compute_sha256(foto)

                # Busca si ya existe un blob para este StudentGeneral
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

                # limpiar ImageField (evitar filesystem)
                g.foto_ficha.delete(save=False)
                g.foto_ficha = None
                g.save(update_fields=["foto_ficha"])

            

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
            logger.info(f"Académicos guardados ficha={ficha.id}")
        else:
            messages.error(request, "Revise los campos de Antecedentes Académicos.")
            logger.warning("Académicos inválidos")

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
            logger.info(f"Mórbidos guardados ficha={ficha.id}")
        else:
            messages.error(request, "Revise los campos de Antecedentes Mórbidos.")
            logger.warning("Mórbidos inválidos")

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
            logger.info(f"Vacunas/Serología guardadas ficha={ficha.id}")
        else:
            messages.error(request, "Revise los campos de Vacunas/Serología.")
            logger.warning("Vacunas/Serología inválidas")

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

            # === CAMBIO: borrar existentes del/los mismo(s) item(s) antes de crear nuevos ===
            if input_name == "ci_archivos[]":
                _delete_existing_docs(ficha, [DocumentItem.CI_FRENTE, DocumentItem.CI_REVERSO])
            else:
                _delete_existing_docs(ficha, [item])
            # ===============================================================================

            for idx, f in enumerate(files):
                actual_item = item
                if input_name == "ci_archivos[]":
                    actual_item = DocumentItem.CI_FRENTE if idx == 0 else DocumentItem.CI_REVERSO
                _doc_create_with_blob(ficha, section, actual_item, f)

        _save_ci_rule_guard(ficha)
        logger.info(f"Documentos procesados ficha={ficha.id}")

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
            logger.info(f"Declaración guardada ficha={ficha.id}")
        else:
            messages.error(request, "Revise los campos de Declaración.")
            logger.warning("Declaración inválida")

        # Estado post-guardado (estudiante)
        if user.rol == "STUDENT":
            finalizar = request.POST.get("finalizar")
            ficha.estado_global = StudentFicha.Estado.ENVIADA if finalizar else StudentFicha.Estado.DRAFT
            ficha.save()
            logger.info(f"Estado final de la ficha={ficha.id} estado={ficha.estado_global}")
            logger.info(f"Académicos guardados ficha={ficha.id}")

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
    template_name = "dashboards/revision_pendientes.html"  # <- usar el nuevo shell con sidebar

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
        logger.info(f"Estado final de la ficha={ficha.id} estado={ficha.estado_global}")
        logger.info(f"Académicos guardados ficha={ficha.id}")
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
        logger.info(f"Estado final de la ficha={ficha.id} estado={ficha.estado_global}")
        logger.info(f"Académicos guardados ficha={ficha.id}")
        return JsonResponse({"ok": True, "estado": ficha.estado_global})


def home(request):
    return redirect('dashboard_estudiante')


def logout_to_login(request):
    logout(request)
    return redirect('login')


@login_required
def dashboard_estudiante(request):
    ficha = StudentFicha.objects.filter(user=request.user, is_activa=True).first()
    documentos = StudentDocuments.objects.filter(ficha=ficha).order_by("-uploaded_at") if ficha else []
    
    ctx = {
        "ficha": ficha,
        "documentos": documentos,
        "ficha_pdf_disponible": bool(ficha),
        "is_revisor": request.user.rol == "REVIEWER",
    }
    return render(request, 'dashboards/estudiante.html', ctx)


@login_required
def ficha_pdf(request):
    """
    Ficha (HTML->PDF) + por CADA anexo: portada (título) + contenido.
    PDFs se anexan tal cual; imágenes se convierten a 1 página A4 centrada.
    """
    ficha = StudentFicha.objects.filter(user=request.user, is_activa=True).first()
    if not ficha:
        return redirect("ficha")

    # --- DTO base + foto (prioriza blob; fallback archivo/URL/base64) ---
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
            except:
                foto_path = None

            try:
                foto_url = request.build_absolute_uri(generales.foto_ficha.url)
            except:
                foto_url = None

            try:
                with generales.foto_ficha.open("rb") as f:
                    foto_b64 = base64.b64encode(f.read()).decode("ascii")
            except:
                pass

    dto.setdefault("generales", {})
    dto["generales"]["foto_ficha_path"] = foto_path
    dto["generales"]["foto_ficha_url"] = foto_url
    dto["generales"]["foto_ficha_b64"] = foto_b64

    # -------- PDF de la ficha (portada + contenido) --------
    base_pdf = pdf_utils.render_html_to_pdf_bytes("pdf/ficha_pdf.html", {
        "ficha": ficha,
        "data": dto,
        "comentarios": ficha.comentarios_ficha.all().order_by("-fecha"),
    })

    streams = [base_pdf]

    docs_qs = ficha.documents.select_related("blob").order_by("uploaded_at", "id")

    for doc in docs_qs:
        raw = None
        if getattr(doc, "blob", None) and doc.blob.data:
            raw = bytes(doc.blob.data)
        elif doc.file:
            try:
                raw = doc.file.read()
            except:
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

User = get_user_model()

def register(request):
    if request.method == "POST":
        email = request.POST.get("email")
        rol = request.POST.get("rol")
        password1 = request.POST.get("password1")
        password2 = request.POST.get("password2")

        if password1 != password2:
            messages.error(request, "Las contraseñas no coinciden.")
            return redirect("register")

        try:
            User.objects.create_user(email=email, password=password1, rol=rol)
            messages.success(request, "Usuario creado correctamente.")
            return redirect("login")  # login ya existe en el proyecto

        except Exception as e:
            messages.error(request, f"Error al crear usuario: {e}")
            return redirect("register")

    return render(request, "accounts/register.html")

# ✅ ESTA FUNCIÓN VA COMPLETAMENTE FUERA DE OTRAS FUNCIONES
@login_required
def detalle_documento(request, id):
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

    return render(request, "accounts/detalle_documento.html", {
        "documento": documento,
        "comentarios": comentarios,
        "form": form,
        "puede_comentar": puede_comentar
    })

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

@login_required
def landing_por_rol(request):
    if getattr(request.user, "rol", "") == "REVIEWER":
        return redirect("revisiones_pendientes")
    # if request.user.rol == "ADMIN": return redirect("/admin/")
    return dashboard_estudiante(request)