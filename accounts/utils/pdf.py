from io import BytesIO
from typing import Iterable, Optional, Tuple

from django.template.loader import get_template
from xhtml2pdf import pisa
from PyPDF2 import PdfReader, PdfWriter
from PIL import Image


def render_html_to_pdf_bytes(template_name: str, context: dict) -> bytes:
    """
    Renderiza un template HTML a PDF (bytes) usando xhtml2pdf (pisa).
    """
    html = get_template(template_name).render(context)
    src = BytesIO(html.encode("utf-8"))
    out = BytesIO()
    pisa.CreatePDF(src, dest=out, encoding="utf-8")
    return out.getvalue()


def image_bytes_to_singlepage_pdf_bytes(img_bytes: bytes) -> bytes:
    """
    Convierte bytes de imagen (PNG/JPG) a un PDF de 1 página.
    """
    bio = BytesIO(img_bytes)
    img = Image.open(bio).convert("RGB")
    out = BytesIO()
    img.save(out, format="PDF")
    return out.getvalue()


def merge_pdf_streams(streams: Iterable[bytes]) -> bytes:
    """
    Fusiona varios PDFs (en bytes) en un solo PDF (bytes).
    """
    writer = PdfWriter()
    for pdf_bytes in streams:
        reader = PdfReader(BytesIO(pdf_bytes))
        for page in reader.pages:
            writer.add_page(page)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def classify_attachment(file_name: Optional[str], file_mime: Optional[str]) -> Tuple[bool, bool]:
    """
    Retorna (is_pdf, is_image) según nombre/mime.
    """
    name = (file_name or "").lower()
    mime = (file_mime or "").lower()
    is_pdf = name.endswith(".pdf") or mime == "application/pdf"
    is_img = any(name.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp")) or mime.startswith("image/")
    return is_pdf, is_img
