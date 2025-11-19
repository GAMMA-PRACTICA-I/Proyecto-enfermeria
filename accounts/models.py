from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.core.validators import FileExtensionValidator
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver


# =========================
#  Helpers rutas archivos
# =========================

def general_png_upload_path(instance, filename):
    # Evita fallar si aún no hay ficha asociada
    ficha_id = getattr(instance, "ficha_id", None) or "unknown"
    return f"student_docs/ficha_{ficha_id}/foto_ficha.png"


def _foto_ficha_path(instance, filename):
    # Usado en migraciones antiguas
    ficha_id = getattr(instance, "ficha_id", None) or "unknown"
    return f"student_docs/ficha_{ficha_id}/foto_ficha.png"


def student_upload_path(instance, filename):
    return f"student_docs/ficha_{instance.ficha_id}/{filename}"


# =========================
#  Usuarios / Roles
# =========================

class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email, password, **extra):
        if not email:
            raise ValueError("Email requerido")
        email = self.normalize_email(email)
        u = self.model(email=email, **extra)
        u.set_password(password)
        u.save(using=self._db)
        return u

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, password, **extra)

    def create_superuser(self, email, password, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self._create(email, password, **extra)


class User(AbstractUser):
    class Rol(models.TextChoices):
        STUDENT = "STUDENT", "Estudiante"
        REVIEWER = "REVIEWER", "Revisor"
        ADMIN = "ADMIN", "Admin"

    username = None
    email = models.EmailField(unique=True, db_index=True)
    rol = models.CharField(
        max_length=10,
        choices=Rol.choices,
        db_index=True,
        default=Rol.STUDENT,
    )
    rut = models.CharField(max_length=20, blank=True, null=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["rol"]

    objects = UserManager()

    def __str__(self):
        return f"{self.email} ({self.get_rol_display()})"


# =========================
#  Ficha (contenedor)
# =========================

class StudentFicha(models.Model):
    class Estado(models.TextChoices):
        # Añadimos "OK" porque FinalizeReviewAPI asigna "OK" directamente
        OK = "OK", "OK"
        DRAFT = "DRAFT", "Borrador"
        ENVIADA = "ENVIADA", "Enviada por estudiante"
        EN_REVISION = "EN_REVISION", "En revisión"
        OBSERVADA = "OBSERVADA", "Observada"
        APROBADA = "APROBADA", "Aprobada"
        RECHAZADA = "RECHAZADA", "Rechazada"

    is_activa = models.BooleanField(default=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fichas",
    )
    estado_global = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.DRAFT,
        db_index=True,
    )
    observaciones_globales = models.TextField(blank=True, null=True)
    revisado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="fichas_revisadas",
    )
    revisado_en = models.DateTimeField(null=True, blank=True)
    pdf_resultado_path = models.CharField(max_length=500, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "student_ficha"
        indexes = [
            models.Index(
                fields=["user", "estado_global"],
                name="idx_ficha_user_estado",
            ),
            models.Index(
                fields=["user", "is_activa"],
                name="idx_ficha_user_activa",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(is_activa=True),
                name="uniq_ficha_activa_por_usuario",
            )
        ]

    def save(self, *args, **kwargs):
        """Si esta ficha queda activa, desactiva cualquier otra activa del mismo usuario."""
        becoming_active = self.is_activa
        super().save(*args, **kwargs)
        if becoming_active:
            StudentFicha.objects.filter(
                user_id=self.user_id,
                is_activa=True,
            ).exclude(pk=self.pk).update(is_activa=False)

    def __str__(self):
        return f"Ficha #{self.id} de {self.user.email} ({self.get_estado_global_display()})"


# =========================
#  Revisión de campos
# =========================

class FieldReview(models.Model):
    """
    Este modelo es el que espera FieldReviewAPI en views.py
    """

    class Status(models.TextChoices):
        OK = "OK", "OK"
        OBSERVADO = "OBSERVADO", "Observado"

    ficha = models.ForeignKey(
        StudentFicha,
        on_delete=models.CASCADE,
        related_name="field_reviews",
    )
    # opcional, por si quieres agrupar (Generales, Académicos, etc.)
    section = models.CharField(max_length=80, db_index=True, blank=True, default="")
    field_key = models.CharField(max_length=120, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        db_index=True,
    )
    notes = models.TextField(blank=True, null=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="field_reviews_done",
    )
    reviewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "student_field_review"
        unique_together = [("ficha", "field_key")]
        indexes = [
            models.Index(
                fields=["ficha", "field_key"],
                name="idx_field_ficha_key",
            ),
            models.Index(
                fields=["ficha", "status"],
                name="idx_field_ficha_status",
            ),
        ]

    def __str__(self):
        return f"{self.ficha_id} • {self.section} • {self.field_key} → {self.status}"


# =========================
#  Comentarios
# =========================

class ComentarioDocumento(models.Model):
    order = models.IntegerField(default=0, db_index=True)
    documento = models.ForeignKey(
        "StudentDocuments",
        on_delete=models.CASCADE,
        related_name="comentarios",
    )
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    mensaje = models.TextField()
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comentario de {self.autor} en {self.documento}"


class ComentarioFicha(models.Model):
    ficha = models.ForeignKey(
        StudentFicha,
        on_delete=models.CASCADE,
        related_name="comentarios_ficha",
    )
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    mensaje = models.TextField()
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comentario de {self.autor.email} en ficha {self.ficha.id}"


# =========================
#  I. Antecedentes Generales
# =========================

class StudentGenerales(models.Model):
    class Seguro(models.TextChoices):
        FONASA_A = "FONASA_A", "FONASA A"
        FONASA_B = "FONASA_B", "FONASA B"
        FONASA_C = "FONASA_C", "FONASA C"
        FONASA_D = "FONASA_D", "FONASA D"
        ISAPRE = "ISAPRE", "ISAPRE"
        FUERZAS_ARMADAS = "FUERZAS_ARMADAS", "Fuerzas Armadas"
        OTRO = "OTRO", "Otro"

    # NULLABLE para primera migración
    ficha = models.OneToOneField(
        StudentFicha,
        on_delete=models.CASCADE,
        related_name="generales",
        null=True,
        blank=True,
    )

    nombre_legal = models.CharField(max_length=120, null=True, blank=True)
    rut = models.CharField(max_length=20, null=True, blank=True, db_index=True)
    genero = models.CharField(max_length=20, null=True, blank=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)

    telefono_celular = models.CharField(max_length=30, null=True, blank=True)
    direccion_actual = models.TextField(null=True, blank=True)
    direccion_origen = models.TextField(null=True, blank=True)

    contacto_emergencia_nombre = models.CharField(max_length=120, null=True, blank=True)
    contacto_emergencia_parentesco = models.CharField(max_length=80, null=True, blank=True)
    contacto_emergencia_telefono = models.CharField(max_length=30, null=True, blank=True)

    centro_salud = models.CharField(max_length=120, null=True, blank=True)

    seguro = models.CharField(
        max_length=20,
        choices=Seguro.choices,
        null=True,
        blank=True,
    )
    seguro_detalle = models.CharField(max_length=120, null=True, blank=True)

    foto_ficha = models.ImageField(
        upload_to=general_png_upload_path,
        null=True,
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=["png"])],
        help_text="Solo PNG",
    )

    class Meta:
        db_table = "student_general"

    def __str__(self):
        return f"Generales - Ficha {self.ficha_id}"


class StudentGeneralPhotoBlob(models.Model):
    general = models.OneToOneField(
        StudentGenerales,
        on_delete=models.CASCADE,
        related_name="photo_blob",
    )
    mime = models.CharField(max_length=100, default="image/png")
    data = models.BinaryField()  # bytes reales
    size_bytes = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "student_general_photo_blob"
        indexes = [
            models.Index(fields=["sha256"], name="idx_genphotoblob_sha256"),
        ]

    def __str__(self):
        return f"FotoBlob General#{self.general_id} ({self.mime}, {self.size_bytes}B)"


# =========================
#  II. Antecedentes Académicos
# =========================

class StudentAcademicos(models.Model):
    # NULLABLE para primera migración
    ficha = models.OneToOneField(
        StudentFicha,
        on_delete=models.CASCADE,
        related_name="academicos",
        null=True,
        blank=True,
    )

    nombre_social = models.CharField(max_length=120, null=True, blank=True)
    carrera = models.CharField(max_length=120, null=True, blank=True)
    anio_cursa = models.PositiveSmallIntegerField(null=True, blank=True)
    estado = models.CharField(max_length=50, null=True, blank=True)
    asignatura = models.CharField(max_length=160, null=True, blank=True)

    correo_institucional = models.EmailField(null=True, blank=True)
    correo_personal = models.EmailField(null=True, blank=True)

    class Meta:
        db_table = "student_academic"

    def __str__(self):
        return f"Académicos - Ficha {self.ficha_id}"


# =========================
#  III. Antecedentes Mórbidos
# =========================

class StudentMedicos(models.Model):
    class GrupoSang(models.TextChoices):
        A_POS = "A+", "A+"
        A_NEG = "A-", "A-"
        B_POS = "B+", "B+"
        B_NEG = "B-", "B-"
        AB_POS = "AB+", "AB+"
        AB_NEG = "AB-", "AB-"
        O_POS = "O+", "O+"
        O_NEG = "O-", "O-"

    # NULLABLE para primera migración
    ficha = models.OneToOneField(
        StudentFicha,
        on_delete=models.CASCADE,
        related_name="medicos",
        null=True,
        blank=True,
    )

    alergias_detalle = models.TextField(null=True, blank=True)
    grupo_sanguineo = models.CharField(
        max_length=3,
        choices=GrupoSang.choices,
        null=True,
        blank=True,
    )
    cronicas_detalle = models.TextField(null=True, blank=True)
    medicamentos_detalle = models.TextField(null=True, blank=True)
    otros_antecedentes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "student_medical_background"

    def __str__(self):
        return f"Médicos - Ficha {self.ficha_id}"


# =========================
#  IV. Vacunas / Serología (flexible)
# =========================

class VaccineType(models.TextChoices):
    COVID_19 = "COVID_19", "COVID-19"
    HEPATITIS_B = "HEPATITIS_B", "Hepatitis B"
    VARICELA = "VARICELA", "Varicela"
    INFLUENZA = "INFLUENZA", "Influenza"


class SerologyResultType(models.TextChoices):
    POSITIVA = "POSITIVA", "Positiva"
    NEGATIVA = "NEGATIVA", "Negativa"
    INDETERMINADA = "INDETERMINADA", "Indeterminada"


class VaccineDose(models.Model):
    ficha = models.ForeignKey(
        StudentFicha,
        on_delete=models.CASCADE,
        related_name="vaccine_doses",
    )
    vaccine_type = models.CharField(
        max_length=20,
        choices=VaccineType.choices,
        db_index=True,
    )
    dose_label = models.CharField(max_length=30)
    date = models.DateField()

    class Meta:
        db_table = "student_vaccine_dose"
        indexes = [
            models.Index(
                fields=["ficha", "vaccine_type"],
                name="idx_vax_ficha_type",
            ),
        ]

    def __str__(self):
        return f"{self.get_vaccine_type_display()} - {self.dose_label} ({self.date})"


class SerologyResult(models.Model):
    ficha = models.ForeignKey(
        StudentFicha,
        on_delete=models.CASCADE,
        related_name="serologies",
    )
    pathogen = models.CharField(
        max_length=20,
        choices=VaccineType.choices,
        db_index=True,
    )
    result = models.CharField(
        max_length=15,
        choices=SerologyResultType.choices,
    )
    date = models.DateField()

    class Meta:
        db_table = "student_serology_result"
        indexes = [
            models.Index(
                fields=["ficha", "pathogen"],
                name="idx_sero_ficha_pathogen",
            ),
        ]

    def __str__(self):
        return f"{self.get_pathogen_display()} - {self.get_result_display()} ({self.date})"


# =========================
#  V. Documentación Adjunta
# =========================

class DocumentSection(models.TextChoices):
    GENERALES = "GENERALES", "Antecedentes Generales"
    ACADEMICOS = "ACADEMICOS", "Antecedentes Académicos"
    MORBIDOS = "MORBIDOS", "Antecedentes Mórbidos"
    VACUNAS = "VACUNAS", "Vacunas / Serología"
    ADJUNTA = "ADJUNTA", "Documentación Adjunta"


class DocumentItem(models.TextChoices):
    # Identificación
    CI_FRENTE = "CI_FRENTE", "CI (frente)"
    CI_REVERSO = "CI_REVERSO", "CI (reverso)"
    AUTORIZACION_MEDICA = "AUTORIZACION_MEDICA", "Autorización médica práctica"
    # Certificado alumno regular
    CERT_ALUMNO_REGULAR = "CERT_ALUMNO_REGULAR", "Certificado de Alumno Regular"

    # Vacunas/Serologías (adjuntos)
    HEPB_CERT = "HEPB_CERT", "Cert. Hepatitis B"
    VARICELA_IGG = "VARICELA_IGG", "Serología Varicela (IgG)"
    INFLUENZA_CERT = "INFLUENZA_CERT", "Cert. Influenza"
    SARS_COV_2_MEVACUNO = "SARS_COV_2_MEVACUNO", "Cert. MeVacuno (SARS-CoV-2)"

    # Cursos
    CURSO_INTRO_COVID = "CURSO_INTRO_COVID", "Curso Introducción COVID (OMS)"
    CURSO_EPP = "CURSO_EPP", "Curso EPP"
    CURSO_IAAS = "CURSO_IAAS", "Curso IAAS (OMS)"
    CURSO_RCP_BLS = "CURSO_RCP_BLS", "Curso RCP/BLS"
    INDUCCION_CC = "INDUCCION_CC", "Inducción Campo Clínico (SS Biobío)"

    # Médicos vinculados a campos
    ALERGIAS_CERT = "ALERGIAS_CERT", "Certificado Alergias"
    ENFERMEDADES_CERT = "ENFERMEDADES_CERT", "Certificado Enfermedades"
    MEDICAMENTOS_CERT = "MEDICAMENTOS_CERT", "Certificado Medicamentos"
    OTROS_ANTECEDENTES_CERT = "OTROS_ANTECEDENTES_CERT", "Certificado Otros Antecedentes"


class DocumentReviewStatus(models.TextChoices):
    ADJUNTADO = "ADJUNTADO", "Adjuntado"
    REVISADO_NO_OK = "REVISADO_NO_OK", "Revisado no ok"
    REVISADO_OK = "REVISADO_OK", "Revisado ok"


class StudentDocuments(models.Model):
    # NULLABLE para primera migración
    ficha = models.ForeignKey(
        StudentFicha,
        on_delete=models.CASCADE,
        related_name="documents",
        null=True,
        blank=True,
    )
    section = models.CharField(
        max_length=15,
        choices=DocumentSection.choices,
        db_index=True,
        null=True,
        blank=True,
    )
    item = models.CharField(
        max_length=30,
        choices=DocumentItem.choices,
        db_index=True,
        null=True,
        blank=True,
    )

    file = models.FileField(
        upload_to=student_upload_path,
        max_length=500,
        blank=True,
        null=True,
    )

    file_name = models.CharField(max_length=255)
    file_mime = models.CharField(max_length=100, blank=True, null=True)
    descripcion = models.TextField(null=True, blank=True)

    order = models.IntegerField(default=0, db_index=True)

    review_status = models.CharField(
        max_length=20,
        choices=DocumentReviewStatus.choices,
        default=DocumentReviewStatus.ADJUNTADO,
        db_index=True,
    )
    review_notes = models.TextField(blank=True, null=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="docs_revisados",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "student_documents"
        indexes = [
            models.Index(
                fields=["ficha", "section", "item"],
                name="idx_doc_ficha_section_item",
            ),
            models.Index(
                fields=["review_status"],
                name="idx_doc_review_status",
            ),
        ]

    def save(self, *args, **kwargs):
        """
        Reemplaza automáticamente documentos previos del mismo (ficha, item).
        Queda solo el más reciente.
        """
        is_creating = self.pk is None
        if is_creating and self.ficha_id and self.item:
            siblings = type(self).objects.filter(
                ficha_id=self.ficha_id,
                item=self.item,
            )
            for d in siblings:
                d.delete()

        super().save(*args, **kwargs)

    def clean(self):
        if self.item in (DocumentItem.CI_FRENTE, DocumentItem.CI_REVERSO):
            qs = StudentDocuments.objects.filter(
                ficha=self.ficha,
                item__in=(DocumentItem.CI_FRENTE, DocumentItem.CI_REVERSO),
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.count() >= 2:
                raise ValidationError(
                    "Ya existen 2 adjuntos de CI (frente/reverso) para esta ficha."
                )

    def __str__(self):
        return f"Doc {self.get_item_display()} (Ficha {self.ficha_id})"


class DocumentReviewLog(models.Model):
    document = models.ForeignKey(
        StudentDocuments,
        on_delete=models.CASCADE,
        related_name="review_logs",
    )
    old_status = models.CharField(
        max_length=20,
        choices=DocumentReviewStatus.choices,
        null=True,
        blank=True,
    )
    new_status = models.CharField(
        max_length=20,
        choices=DocumentReviewStatus.choices,
    )
    notes = models.TextField(blank=True, null=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    reviewed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "student_document_review_log"
        indexes = [
            models.Index(
                fields=["document", "reviewed_at"],
                name="idx_doclog_doc_time",
            ),
        ]

    def __str__(self):
        return f"Log Doc#{self.document_id}: {self.old_status} → {self.new_status}"


# =========================
#  Almacenamiento binario crudo en BD
# =========================

class StudentDocumentBlob(models.Model):
    class Backend(models.TextChoices):
        FILE = "FILE", "File storage (MEDIA/S3)"
        DB = "DB", "Database blob"

    document = models.OneToOneField(
        StudentDocuments,
        on_delete=models.CASCADE,
        related_name="blob",
    )
    storage_backend = models.CharField(
        max_length=8,
        choices=Backend.choices,
        default=Backend.DB,
        db_index=True,
    )
    data = models.BinaryField(null=True, blank=True)
    size_bytes = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "student_document_blob"
        indexes = [
            models.Index(fields=["storage_backend"], name="idx_blob_backend"),
            models.Index(fields=["sha256"], name="idx_blob_sha256"),
        ]

    def __str__(self):
        return f"Blob Doc#{self.document_id} ({self.storage_backend})"


# =========================
#  VI. Declaración
# =========================

class StudentDeclaracion(models.Model):
    # NULLABLE para primera migración
    ficha = models.OneToOneField(
        StudentFicha,
        on_delete=models.CASCADE,
        related_name="declaracion",
        null=True,
        blank=True,
    )

    nombre_estudiante = models.CharField(max_length=120)
    rut = models.CharField(max_length=20, db_index=True)
    firma = models.CharField(max_length=255, null=True, blank=True)
    fecha = models.DateField(auto_now_add=True)

    class Meta:
        db_table = "student_declaration"

    def __str__(self):
        return f"Declaración Ficha {self.ficha_id} - {self.nombre_estudiante}"


# =========================
#  Tickets de soporte (Mesa de Ayuda)
# =========================

class StudentSupportTicket(models.Model):
    class Estado(models.TextChoices):
        ABIERTO = "ABIERTO", "Abierto"
        CERRADO = "CERRADO", "Cerrado"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="support_tickets",
    )
    ficha = models.ForeignKey(
        StudentFicha,
        on_delete=models.CASCADE,
        related_name="support_tickets",
    )

    tipo_consulta = models.CharField(max_length=100)
    asunto = models.CharField(max_length=200)
    detalle = models.TextField()

    respuesta_admin = models.TextField(blank=True, null=True)
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.ABIERTO,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "student_support_ticket"
        indexes = [
            models.Index(fields=["estado", "created_at"], name="idx_ticket_estado_created"),
        ]

    def __str__(self):
        return f"Ticket #{self.id} ({self.estado}) - {self.user.email}"


# =========================
#  Signals
# =========================

@receiver(post_save, sender=StudentDocuments)
def _replace_old_blobs_same_item(sender, instance: StudentDocuments, created: bool, **kwargs):
    """
    Cada vez que se crea un nuevo StudentDocuments para el mismo (ficha, item),
    borra los documentos anteriores; por on_delete=CASCADE esto elimina también
    sus StudentDocumentBlob asociados.
    """
    if not created:
        return

    siblings_qs = sender.objects.filter(
        ficha=instance.ficha,
        item=instance.item,
    ).exclude(pk=instance.pk).select_related("blob")

    for old_doc in siblings_qs:
        old_doc.delete()
