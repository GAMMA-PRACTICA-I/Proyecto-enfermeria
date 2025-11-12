# accounts/utils/review_map.py
from typing import Dict
from accounts.models import StudentFicha, StudentFieldReview

# Normaliza el nombre de sección guardado en BD a las claves usadas por la plantilla
# Plantilla espera: 'GENERALES', 'ACADEMICOS', 'MORBIDOS', 'DECLARACION'
def _normalize_section(section: str) -> str:
    if not section:
        return "GENERALES"
    s = section.strip().lower()
    if "general" in s:
        return "GENERALES"
    if "acad" in s:
        return "ACADEMICOS"
    if "mórb" in s or "morb" in s or "médic" in s:
        return "MORBIDOS"
    if "declar" in s:
        return "DECLARACION"
    # fallback seguro
    return "GENERALES"

def build_prev_map(ficha: StudentFicha) -> Dict[str, dict]:
    """
    Devuelve un dict con la forma que consume la plantilla revisor_ficha.html.
    {
      'GENERALES':   {'rut': {'status': 'REVISADO_OK'}, ...},
      'ACADEMICOS':  {...},
      'MORBIDOS':    {...},
      'DECLARACION': {...},
    }
    """
    out = {
        "GENERALES": {},
        "ACADEMICOS": {},
        "MORBIDOS": {},
        "DECLARACION": {},
    }

    for r in StudentFieldReview.objects.filter(ficha=ficha).only(
        "section", "field_key", "status"
    ):
        sec = _normalize_section(r.section)
        if r.field_key:
            out.setdefault(sec, {})[r.field_key] = {"status": r.status}
    return out
