from datetime import date
from decimal import Decimal
from typing import Optional, TYPE_CHECKING

from django.db import transaction, IntegrityError
from django.contrib.auth import get_user_model

from apps.common.choices import Currency

from .choices import ConceptLineType, DocumentStatus, DocumentType
from .concept import ConceptLine
from .exceptions import (
    InvalidConceptLine,
    InvalidLineTypeForDocument,
    MissingPeriod,
    MissingRecipient,
    MissingRequiredRelation,
    DuplicatePeriodicReceipt,
    UnmappedConceptLineSign,
    CannotCancelDocument,
)
from .models import BillingDocument
from .numbering import assign_document_number

if TYPE_CHECKING:
    from apps.contacts.models import Contact
    from apps.contracts.models import RentalContract
    from apps.deals.models import Deal
    from apps.users.models import User

User = get_user_model()


# Qué ConceptLineType es válido en cada DocumentType (matriz acordada).
_ALLOWED_LINE_TYPES: dict[str, set[str]] = {
    DocumentType.RENT_RECEIPT: {
        ConceptLineType.RENT, ConceptLineType.MORA,
        ConceptLineType.ADJUSTMENT, ConceptLineType.EXPENSE,
        ConceptLineType.OTHER_CHARGE, ConceptLineType.OTHER_CREDIT,
    },
    DocumentType.COMMISSION_RECEIPT: {
        ConceptLineType.COMMISSION,
        ConceptLineType.OTHER_CHARGE, ConceptLineType.OTHER_CREDIT,
    },
    DocumentType.EXPENSE_RECEIPT: {
        ConceptLineType.EXPENSE,
        ConceptLineType.OTHER_CHARGE, ConceptLineType.OTHER_CREDIT,
    },
    DocumentType.OWNER_STATEMENT: {
        ConceptLineType.RENT, ConceptLineType.MORA,
        ConceptLineType.COMMISSION, ConceptLineType.EXPENSE,
        ConceptLineType.OTHER_CHARGE, ConceptLineType.OTHER_CREDIT,
    },
}


# CONVENCIÓN DE SIGNO:
# - El total se computa desde la óptica del DESTINATARIO del documento:
#   recibo → lo que el inquilino/comprador paga; rendición → lo que el
#   propietario cobra. Ambos totales son positivos en el caso normal.
# - Los conceptos OTHER se nombran desde la óptica de la INMOBILIARIA:
#   OTHER_CHARGE = la agencia carga algo; OTHER_CREDIT = la agencia acredita algo.
#   Su efecto en el total depende del documento (ver cada mapa).
_RECEIPT_SIGN: dict[str, Decimal] = {
    ConceptLineType.RENT: Decimal("1"),
    ConceptLineType.COMMISSION: Decimal("1"),
    ConceptLineType.MORA: Decimal("1"),
    ConceptLineType.ADJUSTMENT: Decimal("1"),
    ConceptLineType.EXPENSE: Decimal("1"),
    ConceptLineType.OTHER_CHARGE: Decimal("1"),
    ConceptLineType.OTHER_CREDIT: Decimal("-1"),
}


_OWNER_STATEMENT_SIGN: dict[str, Decimal] = {
    ConceptLineType.RENT: Decimal("1"),
    ConceptLineType.MORA: Decimal("1"),
    ConceptLineType.COMMISSION: Decimal("-1"),
    ConceptLineType.EXPENSE: Decimal("-1"),
    ConceptLineType.OTHER_CHARGE: Decimal("-1"),   # cargo de la agencia al propietario: descuenta
    ConceptLineType.OTHER_CREDIT: Decimal("1"),    # haber a favor del propietario: suma
}


_UNIQUE_ISSUED_RENT_RECEIPT_CONSTRAINT = "unique_issued_rent_receipt_per_period"

_PERIOD_REQUIRED = {
    DocumentType.RENT_RECEIPT,
    DocumentType.EXPENSE_RECEIPT,
    DocumentType.OWNER_STATEMENT,
}
_PERIODIC_DOCUMENT_TYPES = {
    DocumentType.RENT_RECEIPT,
    DocumentType.EXPENSE_RECEIPT,
}
_PERIODIC_CONSTRAINT_BY_TYPE = {
    DocumentType.RENT_RECEIPT: "unique_issued_rent_receipt_per_period",
    DocumentType.EXPENSE_RECEIPT: "unique_issued_expense_receipt_per_period",
}
_CONTRACT_BASED = {DocumentType.RENT_RECEIPT, DocumentType.EXPENSE_RECEIPT}
_RECIPIENT_EXPLICIT = {DocumentType.COMMISSION_RECEIPT, DocumentType.OWNER_STATEMENT}


def _validate_relations(document_type: str, contract, deal) -> None:
    """Presencia de FK por tipo (invariante en el service, opción B)."""
    if document_type in _CONTRACT_BASED:
        if contract is None:
            raise MissingRequiredRelation(
                f"{document_type} requiere contract."
            )
    elif document_type == DocumentType.COMMISSION_RECEIPT:
        if deal is None:
            raise MissingRequiredRelation(
                "COMMISSION_RECEIPT requiere deal."
            )
    elif document_type == DocumentType.OWNER_STATEMENT:
        if contract is not None or deal is not None:
            raise MissingRequiredRelation(
                "OWNER_STATEMENT no se ancla a un contract ni deal único — "
                "los contratos liquidados van en los renglones."
            )


def _resolve_period(document_type: str, period: date | None) -> date | None:
    """Normaliza period a primer día del mes. None para tipos sin período."""
    if document_type not in _PERIOD_REQUIRED:
        return None
    if period is None:
        raise MissingPeriod(f"{document_type} requiere period.")
    return date(period.year, period.month, 1)


def _resolve_recipient(document_type: str, contract, recipient_contact):
    """Inquilino derivado para contract-based; explícito para el resto."""
    if document_type in _CONTRACT_BASED:
        return contract.tenant_contact
    if document_type in _RECIPIENT_EXPLICIT:
        if recipient_contact is None:
            raise MissingRecipient(
                f"{document_type} requiere recipient_contact explícito."
            )
        return recipient_contact
    raise MissingRecipient(f"document_type desconocido: {document_type}")


def _validate_lines(document_type: str, lines: list[ConceptLine]) -> None:
    if not lines:
        raise InvalidConceptLine("Un comprobante requiere al menos un renglón.")

    allowed = _ALLOWED_LINE_TYPES[document_type]
    for line in lines:
        if line.type not in allowed:
            raise InvalidLineTypeForDocument(
                f"El renglón '{line.type}' no es válido en {document_type}."
            )

    if document_type == DocumentType.OWNER_STATEMENT:
        exempt_from_contract_id = {
            ConceptLineType.OTHER_CHARGE,
            ConceptLineType.OTHER_CREDIT,
        }
        for line in lines:
            if line.type not in exempt_from_contract_id and not line.contract_id:
                raise InvalidConceptLine(
                    "Cada renglón de rendición (salvo OTHER_CHARGE/OTHER_CREDIT) "
                    "requiere contract_id."
                )


def _compute_total(document_type: str, lines: list[ConceptLine]) -> Decimal:
    """Total derivado de los renglones — NO se recibe del caller.
    Signo contextual al document_type (ver _line_sign): un OTHER_CREDIT
    descuenta tanto en un recibo como en una rendición.
    """
    return sum(
        (_line_sign(document_type, line.type) * line.amount for line in lines),
        Decimal("0"),
    )


def create_billing_document(
    *,
    document_type: str,
    lines: list[ConceptLine],
    date: date,
    period: date | None = None,
    contract: Optional["RentalContract"] | None = None,
    deal: Optional["Deal"] | None = None,
    recipient_contact: Optional["Contact"] | None = None,
    currency: str = Currency.ARS,
    actor: Optional["User"] | None = None,
) -> BillingDocument:
    """Emite un comprobante. Único punto válido de creación.

    Valida TODO antes de consumir nextval() — el número se asigna lo más
    tarde posible para minimizar gaps. actor=None = acción del sistema.

    Raises (todos BillingBusinessError, capturables por la view):
        MissingRequiredRelation, MissingRecipient, MissingPeriod,
        InvalidConceptLine, InvalidLineTypeForDocument, DuplicatePeriodicReceipt.
    """
    if document_type not in _ALLOWED_LINE_TYPES:
        raise InvalidLineTypeForDocument(
            f"document_type desconocido: {document_type}"
        )

    # 1. Validaciones puras (sin IO mutante, sin consumir número).
    _validate_relations(document_type, contract, deal)
    resolved_period = _resolve_period(document_type, period)
    recipient = _resolve_recipient(document_type, contract, recipient_contact)
    # Congelado al emitir — mismo argumento que total_amount: lo legalmente
    # significativo no se deriva en lecturas futuras, se persiste en el
    # momento de la emisión. Si el contacto edita su nombre o documento
    # después, este comprobante no se entera — correcto para un documento legal.
    recipient_name = recipient.full_name
    recipient_document_type = recipient.document_type
    recipient_document_number = recipient.document_number
    _validate_lines(document_type, lines)
    total = _compute_total(document_type, lines)
    resolved_currency = contract.currency if contract is not None else currency

    # 2. Guard de doble-ISSUED (solo RENT) — UX. La garantía real es el
    #    índice parcial unique_issued_rent_receipt_per_period.
    if document_type in _PERIODIC_DOCUMENT_TYPES:
        exists = BillingDocument.objects.filter(
            contract=contract,
            document_type=document_type,
            status=DocumentStatus.ISSUED,
            period=resolved_period,
        ).exists()
        if exists:
            raise DuplicatePeriodicReceipt(
                f"Ya existe un {DocumentType(document_type).label.lower()} "
                f"emitido para este período. Cancelá el existente antes de reemitir."
            )

    concept_json = [line.to_json() for line in lines]

    # 3. Emisión: número TARDE, dentro del atomic.
    try:
        with transaction.atomic():
            number = assign_document_number(document_type)
            document = BillingDocument(
                document_type=document_type,
                number=number,
                date=date,
                period=resolved_period,
                total_amount=total,
                currency=resolved_currency,
                concept=concept_json,
                contract=contract,
                deal=deal,
                recipient_contact=recipient,
                recipient_name=recipient_name,
                recipient_document_type=recipient_document_type,
                recipient_document_number=recipient_document_number,
                status=DocumentStatus.ISSUED,
                created_by=actor,
            )
            document.save()
    except IntegrityError as exc:
        constraint_name = _PERIODIC_CONSTRAINT_BY_TYPE.get(document_type)
        if constraint_name and _violates_constraint(exc, constraint_name):
            raise DuplicatePeriodicReceipt(
                f"Ya existe un {DocumentType(document_type).label.lower()} "
                f"emitido para este período (detectado al confirmar en DB — "
                f"dos emisiones simultáneas). Cancelá el existente antes de reemitir."
            ) from exc
        raise

    return document


def _violates_constraint(exc: IntegrityError, constraint_name: str) -> bool:
    """Identifica si el IntegrityError fue disparado por un constraint
    específico, vía el diagnóstico de Postgres — NO parseando el mensaje
    de error como string. psycopg2/psycopg exponen .diag.constraint_name
    en la excepción subyacente que Django envuelve como __cause__."""
    diag = getattr(exc.__cause__, "diag", None)
    return getattr(diag, "constraint_name", None) == constraint_name


def _line_sign(document_type: str, line_type: str) -> Decimal:
    sign_map = (
        _OWNER_STATEMENT_SIGN if document_type == DocumentType.OWNER_STATEMENT
        else _RECEIPT_SIGN
    )
    try:
        return sign_map[line_type]
    except KeyError as exc:
        raise UnmappedConceptLineSign(
            f"Sin signo configurado para line_type='{line_type}' en "
            f"document_type='{document_type}'."
        ) from exc


def _check_sign_maps_complete() -> None:
    """Corre al importar el módulo. Si alguien agrega un ConceptLineType
    a _ALLOWED_LINE_TYPES sin extender el mapa de signos correspondiente,
    Django no levanta — falla en el import, no en el primer comprobante
    real que use esa combinación."""
    for doc_type, allowed in _ALLOWED_LINE_TYPES.items():
        sign_map = _OWNER_STATEMENT_SIGN if doc_type == DocumentType.OWNER_STATEMENT else _RECEIPT_SIGN
        missing = allowed - sign_map.keys()
        if missing:
            raise UnmappedConceptLineSign(
                f"{doc_type}: falta signo para {missing}."
            )


_check_sign_maps_complete()


def cancel_billing_document(
    *,
    document: BillingDocument,
    actor,
) -> BillingDocument:
    """Cancela un comprobante emitido. Único cambio de estado permitido
    post-emisión: ISSUED → CANCELLED.

    Raises:
        CannotCancelDocument: si el documento no está en estado ISSUED.
    """
    if document.status != DocumentStatus.ISSUED:
        raise CannotCancelDocument(
            "Solo se pueden cancelar comprobantes en estado emitido."
        )
    document.status = DocumentStatus.CANCELLED
    document.updated_by = actor
    document.save(update_fields=["status", "updated_by", "updated_at"])
    return document
