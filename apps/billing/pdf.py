"""Generación del comprobante PDF de BillingDocument.

Presentación pura: recibe un documento ya cargado, devuelve bytes.
On-demand en request-time (decisión S5/c4): un BillingDocument emitido
es inmutable — regenerar da siempre el mismo resultado, no se persiste
nada en R2. "Compartir" (V1.1) revisará esto: necesita objeto
persistido + URL tokenizada fuera de /backoffice/.

build_pdf_context está separado a propósito: los tests de presentación
aseveran sobre el contexto/HTML, no sobre los bytes del PDF.
"""

from django.conf import settings
from django.template.loader import render_to_string
from django.utils.text import slugify
from weasyprint import HTML

from .choices import DocumentStatus, DocumentType
from .display import enrich_lines_for_display, month_label, property_label


def render_document_pdf(document) -> bytes:
    html = render_to_string("billing/pdf/document.html", build_pdf_context(document))
    return HTML(string=html).write_pdf()


def build_pdf_context(document) -> dict:
    is_owner_statement = document.document_type == DocumentType.OWNER_STATEMENT
    return {
        "document": document,
        "type_label": DocumentType(document.document_type).label,
        "recipient_label": "Rendición a" if is_owner_statement else "Recibido de",
        "enriched_lines": enrich_lines_for_display(document),
        "period_label": month_label(document.period) if document.period else "",
        "property_label": property_label(document),
        "is_cancelled": document.status == DocumentStatus.CANCELLED,
        "agency": {
            "name": settings.AGENCY_NAME,
            "cuit": settings.AGENCY_CUIT,
            "address": settings.AGENCY_ADDRESS,
            "phone": settings.AGENCY_PHONE,
            "email": settings.AGENCY_EMAIL,
        },
    }


def document_pdf_filename(document) -> str:
    slug = slugify(DocumentType(document.document_type).label)
    return f"{slug}-{document.number:04d}.pdf"