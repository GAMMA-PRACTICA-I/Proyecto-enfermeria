from io import BytesIO
from typing import Iterable, Optional, Tuple
import base64

from django.template.loader import get_template
from xhtml2pdf import pisa
from PyPDF2 import PdfReader, PdfWriter


def render_html_to_pdf_bytes(template_name: str, context: dict) -> bytes:
    """
    Renderiza un template HTML a PDF (bytes) usando xhtml2pdf (pisa).
    """
    html = get_template(template_name).render(context)
    src = BytesIO(html.encode("utf-8"))
    out = BytesIO()
    pisa.CreatePDF(src, dest=out, encoding="utf-8")
    return out.getvalue()


def title_page_pdf_bytes(title: str, subtitle: Optional[str] = None) -> bytes:
    def _esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    subtitle_html = f"<div class='sub'>{_esc(subtitle)}</div>" if subtitle else ""
    html = f"""
    <html>
      <head>
        <meta charset="utf-8"/>
        <style>
          @page {{ size: A4; margin: 2.5cm; }}
          body {{ font-family: Helvetica, Arial, sans-serif; }}
          .wrap {{
            height: 24cm; display: flex; flex-direction: column;
            align-items: center; justify-content: center; text-align: center;
          }}
          h1 {{ font-size: 24pt; margin: 0 0 8px 0; }}
          .sub {{ font-size: 12pt; color: #444; }}
        </style>
      </head>
      <body>
        <div class="wrap">
          <h1>{_esc(title)}</h1>
          {subtitle_html}
        </div>
      </body>
    </html>
    """
    src = BytesIO(html.encode("utf-8"))
    out = BytesIO()
    pisa.CreatePDF(src, dest=out, encoding="utf-8")
    return out.getvalue()




# pdf.py

def image_bytes_to_singlepage_pdf_bytes(img_bytes: bytes, mime: str = "image/png") -> bytes:
    """
    Convierte bytes de imagen a un PDF A4 de 1 página, centrado y con márgenes.
    (Ajustado para evitar estiramiento)
    """
    b64 = base64.b64encode(img_bytes).decode("ascii")
    html = f"""
    <html>
      <head>
        <meta charset="utf-8"/>
        <style>
          @page {{ size: A4; margin: 2cm; }}
          body {{ margin:0; padding:0; }}
          .frame {{
            width: 100%; height: 27.7cm;
            display: flex; align-items: center; justify-content: center;
          }}
          /* === CAMBIO CLAVE: Reducir el tamaño para que no ocupe el 100% === */
          img {{ 
            max-width: 50%; /* Ocupa como máximo la mitad del ancho de la página */
            max-height: 50%; /* Ocupa como máximo la mitad del alto de la página */
            width: auto; /* Evita forzar el estiramiento */
            height: auto;
            border: 1px solid #ccc; /* Borde opcional para visualización */
          }}
        </style>
      </head>
      <body>
        <div class="frame">
          <img src="data:{mime};base64,{b64}" alt="anexo"/>
        </div>
      </body>
    </html>
    """
    src = BytesIO(html.encode("utf-8"))
    out = BytesIO()
    pisa.CreatePDF(src, dest=out, encoding="utf-8")
    return out.getvalue()


def merge_pdf_streams(streams: Iterable[bytes]) -> bytes:
    """
    Fusiona varios PDFs (en bytes) en un solo PDF (bytes).
    """
    writer = PdfWriter()
    for pdf_bytes in streams:
        if not pdf_bytes:
            continue
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
