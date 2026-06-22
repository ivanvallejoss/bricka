from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from django.db.models import QuerySet

from apps.contracts.choices import ContractStatus

from .choices import DocumentStatus, DocumentType, PaymentStatus
from .models import BillingDocument


from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from apps.contracts.models import RentalContract # Import solo a modo de type hint


def _period_start(as_of: date) -> date:
    """Normaliza cualquier fecha al primer día de su mes.

    period se persiste siempre como primer-día-del-mes (ver BillingDocument).
    El badge consulta sobre ese valor normalizado.
    """
    return date(as_of.year, as_of.month, 1)


def get_rental_payment_status(
    contracts: Iterable["RentalContract"],
    *,
    as_of: date,
) -> dict[UUID, str]:
    """Estado de pago del MES CORRIENTE para una lista de contratos.

    V1 — Lectura "mes corriente", consistente con calculate_mora:
    el badge mide únicamente el mes de `as_of`, no rastrea períodos
    adeudados anteriores. Deuda multi-período → V2 con RentPeriod.

    Solo los contratos ACTIVE reciben estado real. El resto → NOT_APPLICABLE.

    Resuelve los N contratos en UNA query a BillingDocument:
    - PAID    → existe RENT_RECEIPT issued para (contract, period actual)
    - OVERDUE → no existe y as_of > payment_due_day del mes
    - PENDING → no existe y as_of <= payment_due_day del mes

    Recibe los OBJETOS contrato (no IDs): usa payment_due_day y status
    de cada uno, evitando un segundo query a contracts.

    Returns: dict contract_id → PaymentStatus value.
    """
    contracts = list(contracts)
    if not contracts:
        return {}

    period = _period_start(as_of)

    active_ids = [
        c.id for c in contracts
        if c.status == ContractStatus.ACTIVE
    ]

    # Única query: qué contratos activos ya tienen recibo issued del período.
    paid_ids = set(
        BillingDocument.objects.filter(
            contract_id__in=active_ids,
            document_type=DocumentType.RENT_RECEIPT,
            status=DocumentStatus.ISSUED,
            period=period,
        ).values_list("contract_id", flat=True)
    )

    result: dict[UUID, str] = {}
    for contract in contracts:
        if contract.status != ContractStatus.ACTIVE:
            result[contract.id] = PaymentStatus.NOT_APPLICABLE
            continue

        if contract.id in paid_ids:
            result[contract.id] = PaymentStatus.PAID
            continue

        due_day = date(as_of.year, as_of.month, contract.payment_due_day)
        if as_of > due_day:
            result[contract.id] = PaymentStatus.OVERDUE
        else:
            result[contract.id] = PaymentStatus.PENDING

    return result


def get_recent_documents_for_contract(contract_id: UUID, limit: int = 4) -> QuerySet:
    return (
        BillingDocument.objects
        .filter(contract_id=contract_id)
        .order_by("-date", "-number")[:limit]
    )

def get_billing_document_count_for_contract(contract_id: UUID) -> int:
    return BillingDocument.objects.filter(contract_id=contract_id).count()


def get_recent_documents_for_contact(contact_id: UUID, limit: int = 5) -> QuerySet:
    return (
        BillingDocument.objects
        .filter(recipient_contact_id=contact_id)
        .order_by("-date", "-number")[:limit]
    )