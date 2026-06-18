from django.db import connection

from .choices import DocumentType
from .exceptions import UnmappedDocumentType


_SEQUENCE_BY_DOCUMENT_TYPE: dict[str, str] = {
    DocumentType.RENT_RECEIPT: "billing_rent_receipt_seq",
    DocumentType.COMMISSION_RECEIPT: "billing_commission_receipt_seq",
    DocumentType.EXPENSE_RECEIPT: "billing_expense_receipt_seq",
    DocumentType.OWNER_STATEMENT: "billing_owner_statement_seq",
}


def assign_document_number(document_type: str) -> int:
    """Consume el siguiente número correlativo para el document_type dado.

    SIDE-EFFECT: avanza la PostgreSQL sequence de forma irreversible.
    nextval() NO se revierte con rollback — de ahí la posibilidad de gaps
    (trade-off aceptado para V1, ver docs/decisions/design.md).

    Por eso NO vive en selectors.py (que solo lee). El service debe
    llamar esta función lo más TARDE posible en el flujo de emisión —
    después de validar todo — para minimizar la ventana donde un número
    se consume y el documento no llega a commitear.

    Raises:
        UnmappedDocumentType: si el tipo no tiene sequence configurada.
    """
    try:
        sequence_name = _SEQUENCE_BY_DOCUMENT_TYPE[document_type]
    except KeyError as exc:
        raise UnmappedDocumentType(document_type) from exc

    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval(%s)", [sequence_name])
        return cursor.fetchone()[0]