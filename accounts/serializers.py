"""
Serializadores simples sin depender de DRF (para no introducir nuevas dependencias).
Si luego quieres migrar a DRF, puedes reemplazarlos por ModelSerializers sin cambiar vistas.
"""
import base64 
from dataclasses import dataclass, asdict
from typing import List, Optional
from accounts.models import (
    StudentFicha, StudentGeneral, StudentAcademic, StudentMedicalBackground,
    VaccineDose, SerologyResult,
    StudentDocuments, StudentDocumentBlob, DocumentReviewLog, StudentDeclaration
)


@dataclass
class VaccineDoseDTO:
    vaccine_type: str
    dose_label: str
    date: str

    @staticmethod
    def from_model(m: VaccineDose) -> "VaccineDoseDTO":
        return VaccineDoseDTO(
            vaccine_type=m.vaccine_type,
            dose_label=m.dose_label,
            date=m.date.isoformat(),
        )


@dataclass
class SerologyResultDTO:
    pathogen: str
    result: str
    date: str

    @staticmethod
    def from_model(m: SerologyResult) -> "SerologyResultDTO":
        return SerologyResultDTO(
            pathogen=m.pathogen,
            result=m.result,
            date=m.date.isoformat(),
        )


@dataclass
class DocumentDTO:
    id: int
    section: str
    item: str
    file_name: str
    file_mime: Optional[str]
    review_status: str
    reviewed_by: Optional[str]
    reviewed_at: Optional[str]

    @staticmethod
    def from_model(m: StudentDocuments) -> "DocumentDTO":
        return DocumentDTO(
            id=m.id,
            section=m.section,
            item=m.item,
            file_name=m.file_name,
            file_mime=m.file_mime,
            review_status=m.review_status,
            reviewed_by=(m.reviewed_by.email if m.reviewed_by else None),
            reviewed_at=(m.reviewed_at.isoformat() if m.reviewed_at else None),
        )


@dataclass
class FichaDTO:
    id: int
    estado_global: str
    user_email: str
    generales: Optional[dict]
    academicos: Optional[dict]
    medicos: Optional[dict]
    vaccines: List[VaccineDoseDTO]
    serologies: List[SerologyResultDTO]
    documents: List[DocumentDTO]
    declaracion: Optional[dict]

    @staticmethod
    def from_model(ficha: StudentFicha) -> "FichaDTO":
        generales = None
        if hasattr(ficha, "generales") and ficha.generales:
            g = ficha.generales
            def _png_to_b64(fieldfile):
                if not fieldfile:
                    return None
                try:
                     with fieldfile.open("rb") as f:
                            return base64.b64encode(f.read()).decode("ascii")
                except Exception:
                        return None
                
            generales = {
                "nombre_legal": g.nombre_legal,
                "rut": g.rut,
                "genero": g.genero,
                "fecha_nacimiento": g.fecha_nacimiento.isoformat() if g.fecha_nacimiento else None,
                "telefono_celular": g.telefono_celular,
                "direccion_actual": g.direccion_actual,
                "direccion_origen": g.direccion_origen,
                "contacto_emergencia_nombre": g.contacto_emergencia_nombre,
                "contacto_emergencia_parentesco": g.contacto_emergencia_parentesco,
                "contacto_emergencia_telefono": g.contacto_emergencia_telefono,
                "centro_salud": g.centro_salud,
                "seguro": g.seguro,
                "seguro_detalle": g.seguro_detalle,
                "foto_ficha_b64": _png_to_b64(getattr(g, "foto_ficha", None)),
            }

        academicos = None
        if hasattr(ficha, "academicos") and ficha.academicos:
            a = ficha.academicos
            academicos = {
                "nombre_social": a.nombre_social,
                "carrera": a.carrera,
                "anio_cursa": a.anio_cursa,
                "estado": a.estado,
                "asignatura": a.asignatura,
                "correo_institucional": a.correo_institucional,
                "correo_personal": a.correo_personal,
            }

        medicos = None
        if hasattr(ficha, "medicos") and ficha.medicos:
            m = ficha.medicos
            medicos = {
                "alergias_detalle": m.alergias_detalle,
                "grupo_sanguineo": m.grupo_sanguineo,
                "cronicas_detalle": m.cronicas_detalle,
                "medicamentos_detalle": m.medicamentos_detalle,
                "otros_antecedentes": m.otros_antecedentes,
            }

        vaccines = [VaccineDoseDTO.from_model(v) for v in ficha.vaccine_doses.all()]
        serologies = [SerologyResultDTO.from_model(s) for s in ficha.serologies.all()]
        documents = [DocumentDTO.from_model(d) for d in ficha.documents.all()]

        declaracion = None
        if hasattr(ficha, "declaracion") and ficha.declaracion:
            d = ficha.declaracion
            declaracion = {
                "nombre_estudiante": d.nombre_estudiante,
                "rut": d.rut,
                "fecha": d.fecha.isoformat() if d.fecha else None,
                "firma": d.firma,
            }

        return FichaDTO(
            id=ficha.id,
            estado_global=ficha.estado_global,
            user_email=ficha.user.email,
            generales=generales,
            academicos=academicos,
            medicos=medicos,
            vaccines=vaccines,
            serologies=serologies,
            documents=documents,
            declaracion=declaracion,
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["vaccines"] = [asdict(v) for v in self.vaccines]
        data["serologies"] = [asdict(s) for s in self.serologies]
        data["documents"] = [asdict(d) for d in self.documents]
        return data
