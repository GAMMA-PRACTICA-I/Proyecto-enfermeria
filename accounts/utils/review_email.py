# accounts/utils/review_email.py
from typing import Iterable, Optional

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

# Etiquetas amigables por campo (usa las que correspondan a tus field_key)
FIELD_LABELS = {
    "nombre_legal": "Nombre legal",
    "rut": "RUT",
    "genero": "Género",
    "fecha_nacimiento": "Fecha de nacimiento",
    "telefono": "Teléfono",
    "direccion_actual": "Dirección actual",
    "direccion_origen": "Dirección de origen",
    "contacto_emergencia": "Contacto de emergencia",
    "centro_salud": "Centro de salud",
    "seguro": "Seguro",
    # agrega aquí todos los field_key que uses en StudentFieldReview
}


def send_revision_result_email(
    *,
    ficha,
    rechazados: Iterable[dict],
    global_notes: Optional[str],
    aprobado: bool,
    base_url: Optional[str] = None,
) -> None:
    """
    Envía un email al estudiante con el resultado de la revisión.

    - ficha: instancia StudentFicha (debe tener .user.email)
    - rechazados: iterable de dicts con keys:
        - section (opcional, para agrupar)
        - field_key (nombre interno del campo)
        - notes (comentario del revisor)
    - global_notes: comentario general (puede ser None o "")
    - aprobado: True si la ficha quedó aprobada, False si quedó rechazada/observada
    - base_url: URL al dashboard del estudiante (opcional)
    """
    student = getattr(ficha, "user", None)
    student_email = getattr(student, "email", None)

    if not student_email:
        # Sin correo del estudiante no enviamos nada
        return

    # Normalizar lista de rechazados para el template
    rechazados_normalizados = []
    for r in rechazados or []:
        field_key = (r.get("field_key") or "").strip()
        section = (r.get("section") or "").strip()
        notes = (r.get("notes") or "").strip()

        label = FIELD_LABELS.get(field_key, field_key or "Campo sin nombre")
        if not notes:
            notes = "Sin comentario del revisor."

        rechazados_normalizados.append(
            {
                "field_key": field_key,
                "label": label,
                "section": section,
                "notes": notes,
            }
        )

    context = {
        "ficha": ficha,
        "estudiante": student,
        "rechazados": rechazados_normalizados,
        "global_notes": (global_notes or "").strip() or None,
        "base_url": base_url,
    }

    # Elegir asunto y templates según si quedó aprobada o rechazada
    if aprobado:
        subject = (
            f"Tu ficha ha sido APROBADA (#{ficha.id})"
            if hasattr(ficha, "id")
            else "Tu ficha ha sido APROBADA"
        )
        txt_tpl = "emails/revision_aprobada.txt"
        html_tpl = "emails/revision_aprobada.html"
    else:
        subject = (
            f"Tu ficha tiene observaciones (#{ficha.id})"
            if hasattr(ficha, "id")
            else "Tu ficha tiene observaciones"
        )
        txt_tpl = "emails/revision_rechazada.txt"
        html_tpl = "emails/revision_rechazada.html"

    text_body = render_to_string(txt_tpl, context)
    html_body = render_to_string(html_tpl, context)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        to=[student_email],
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send()
