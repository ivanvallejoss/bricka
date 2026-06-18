from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from django.db.models import QuerySet

from .choices import ContractStatus
from .models import RentalContract, RentAdjustment


@dataclass
class ContractFilters:
    status: str | None = None
    property_id: UUID | None = None
    tenant_contact_id: UUID | None = None
    owner_contact_id: UUID | None = None
    deal_id: UUID | None = None


def get_contract_list(filters: ContractFilters | None = None) -> QuerySet:
    """
    Retorna contratos no archivados con relaciones base cargadas.
    El manager default excluye soft-deleted.
    """
    qs = RentalContract.objects.select_related(
        "property",
        "tenant_contact",
        "owner_contact",
    ).all()

    if filters is None:
        return qs

    if filters.status is not None:
        qs = qs.filter(status=filters.status)
    if filters.property_id is not None:
        qs = qs.filter(property_id=filters.property_id)
    if filters.tenant_contact_id is not None:
        qs = qs.filter(tenant_contact_id=filters.tenant_contact_id)
    if filters.owner_contact_id is not None:
        qs = qs.filter(owner_contact_id=filters.owner_contact_id)
    if filters.deal_id is not None:
        qs = qs.filter(deal_id=filters.deal_id)

    return qs


def get_contract_detail(contract_id: UUID) -> RentalContract:
    """
    Retorna un contrato con relaciones completas para vista de detalle.
    Raises RentalContract.DoesNotExist si no existe o está soft-deleted.
    """
    return (
        RentalContract.objects.select_related(
            "property",
            "tenant_contact",
            "owner_contact",
            "deal",
        )
        .get(pk=contract_id)
    )


def get_adjustments_for_contract(contract_id: UUID) -> QuerySet:
    """
    Retorna ajustes de alquiler de un contrato, ordenados por fecha descendente.
    """
    return (
        RentAdjustment.objects
        .filter(contract_id=contract_id)
        .select_related("applied_by")
    )


def get_active_contract_for_property(property_id: UUID) -> RentalContract | None:
    """
    Retorna el contrato ACTIVE de una propiedad, o None si no existe.
    Punto de entrada cross-app — usado por properties/ para determinar
    el estado operacional de la propiedad.
    """
    return RentalContract.objects.filter(
        property_id=property_id,
        status=ContractStatus.ACTIVE,
    ).first()


def get_contracts_due_for_expiration(as_of: date) -> QuerySet:
    """
    Contratos ACTIVE cuya end_date ya pasó.
    Usado por la tarea Celery periódica de expiración automática.
    """
    return RentalContract.objects.filter(
        status=ContractStatus.ACTIVE,
        end_date__lt=as_of,
    )


def get_contracts_due_for_activation(as_of: date) -> QuerySet:
    """
    Contratos SCHEDULED cuya start_date llegó o pasó.
    Usado por la tarea Celery periódica de activación automática.
    """
    return RentalContract.objects.filter(
        status=ContractStatus.SCHEDULED,
        start_date__lte=as_of,
    )


def get_contracts_due_for_adjustment(as_of: date) -> QuerySet:
    """
    Contratos ACTIVE cuya next_adjustment_date llegó o pasó.
    Usado por la tarea Celery periódica de sugerencia de ajuste.
    """
    return RentalContract.objects.filter(
        status=ContractStatus.ACTIVE,
        next_adjustment_date__lte=as_of,
    )


@dataclass
class MoraCalculation:
    days_overdue: int
    daily_rate: Decimal
    total_amount: Decimal


def calculate_mora(contract: RentalContract, as_of: date) -> MoraCalculation | None:
    """
    Calcula mora compuesta diaria si el pago del mes actual está vencido.
    Retorna None si as_of <= payment_due_day del mes en curso.

    Fórmula compuesta: current_price × ((1 + daily_rate/100)^days_overdue − 1)

    Asume pago total — no existe modelo de pagos parciales en V1.
    El resultado es un "consejo" para el agente al emitir el comprobante —
    el valor final siempre puede ser overrideado manualmente.
    """
    payment_due_this_month = date(as_of.year, as_of.month, contract.payment_due_day)
    if as_of <= payment_due_this_month:
        return None

    days_overdue = (as_of - payment_due_this_month).days
    daily_rate = contract.late_fee_percent_daily
    factor = (
        (Decimal("1") + daily_rate / Decimal("100")) ** days_overdue
        - Decimal("1")
    )
    total_amount = (contract.current_price * factor).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    return MoraCalculation(
        days_overdue=days_overdue,
        daily_rate=daily_rate,
        total_amount=total_amount,
    )