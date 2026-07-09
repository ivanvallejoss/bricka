"""Presentación compartida de BillingDocument.

Lógica pura de display usada por views (detail modal, emit form) y por
pdf (comprobante descargable). Vive en módulo propio para que pdf.py no
importe de views.py — views.py va a importar de pdf, y sería un ciclo.
No es service ni selector: no toca DB ni muta estado.
"""

from datetime import date

from .choices import ConceptLineType, DocumentType

_MONTH_NAMES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

SUBTRACTIVE_IN_RECEIPT = {ConceptLineType.OTHER_CREDIT}
SUBTRACTIVE_IN_OWNER_STATEMENT = {
    ConceptLineType.COMMISSION,
    ConceptLineType.EXPENSE,
    ConceptLineType.OTHER_CHARGE,
}


def month_label(d: date) -> str:
    return f"{_MONTH_NAMES[d.month - 1]} {d.year}"


def enrich_lines_for_display(document) -> list[dict]:
    subtractive = (
        SUBTRACTIVE_IN_OWNER_STATEMENT
        if document.document_type == DocumentType.OWNER_STATEMENT
        else SUBTRACTIVE_IN_RECEIPT
    )
    result = []
    for line in document.concept:
        result.append({
            **line,
            "is_subtractive": line["type"] in subtractive,
            "type_label": ConceptLineType(line["type"]).label,
        })
    return result


def property_label(document) -> str:
    """Resuelve la propiedad de un documento: contrato → listing del
    deal → notas de propiedad externa. Misma regla que el elif de
    _section_cobros.html — dos idiomas (template y Python) porque los
    templates no llaman funciones con argumentos; si aparece un tercer
    consumidor, unificar anotando en la view."""
    if document.contract:
        prop = document.contract.property
        return prop.title or prop.address_line
    if document.deal:
        if document.deal.listing:
            prop = document.deal.listing.property
            return prop.title or prop.address_line
        return document.deal.external_property_notes
    return ""