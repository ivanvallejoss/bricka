class UnmappedDocumentType(Exception):
    """El document_type no tiene sequence de numeración configurada.

    Es un ERROR DE PROGRAMACIÓN, no un caso de negocio: significa que
    alguien agregó un DocumentType y olvidó mapear su sequence en
    billing/numbering.py. Debe propagarse hasta romper (y aparecer en
    logs/Sentry), NO ser capturada por la view para mostrar un mensaje
    amable al agente. Mismo tratamiento que DoesNotExist en un service.
    """

    def __init__(self, document_type: str):
        self.document_type = document_type
        super().__init__(
            f"document_type '{document_type}' sin sequence configurada. "
            f"Revisar _SEQUENCE_BY_DOCUMENT_TYPE en billing/numbering.py."
        )

class BillingBusinessError(Exception):
    """Base de errores de negocio de billing. La view los captura y los
    muestra al agente en contexto (partial de modal). NO son errores de
    programación — representan intentos de emisión inválidos.
    """


class InvalidConceptLine(BillingBusinessError):
    """Renglón malformado: amount no positivo, OTHER sin description,
    concept vacío, o renglón de rendición sin contract_id."""


class InvalidLineTypeForDocument(BillingBusinessError):
    """El type de un renglón no está permitido para ese document_type
    (ej: COMMISSION dentro de un RENT_RECEIPT)."""


class MissingRequiredRelation(BillingBusinessError):
    """Falta el FK obligatorio para el document_type (contract o deal)."""


class MissingRecipient(BillingBusinessError):
    """COMMISSION_RECEIPT u OWNER_STATEMENT sin recipient_contact explícito."""


class MissingPeriod(BillingBusinessError):
    """RENT_RECEIPT u OWNER_STATEMENT sin period."""


class UnmappedConceptLineSign(Exception):
    """(document_type, line_type) sin signo configurado en _RECEIPT_SIGN
    o _OWNER_STATEMENT_SIGN. Indica que alguien extendió
    _ALLOWED_LINE_TYPES sin extender el mapa de signos correspondiente."""

class DuplicatePeriodicReceipt(BillingBusinessError):
    """Ya existe un comprobante issued para ese (contract, document_type,
    period). Aplica a los tipos periódicos: RENT_RECEIPT, EXPENSE_RECEIPT.
    Para reemitir, cancelar primero el existente."""