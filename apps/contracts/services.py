from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from django.db import transaction

from apps.properties.choices import PropertyStatus
from apps.properties.services import update_property_status

from .choices import AdjustmentIndex, ContractStatus
from .exceptions import ContractDateConflict, ContractValidationError, InvalidContractStatus
from .models import RentalContract, RentAdjustment

User = get_user_model()


def _check_date_overlap(property_id, start_date, end_date, exclude_contract_id=None):
    qs = RentalContract.objects.filter(
        property_id=property_id,
        status__in=[ContractStatus.ACTIVE, ContractStatus.SCHEDULED],
        start_date__lte=end_date,
        end_date__gte=start_date,
    ).select_related("tenant_contact", "property")
    if exclude_contract_id is not None:
        qs = qs.exclude(pk=exclude_contract_id)
    conflicting = qs.first()
    if conflicting:
        raise ContractDateConflict(
            "Ya existe un contrato cuya vigencia se superpone con las fechas ingresadas.",
            conflicting_contract=conflicting,
        )


def create_rental_contract(
    *,
    property_id: UUID,
    tenant_contact_id: UUID,
    owner_contact_id: UUID,
    deal_id: UUID | None = None,
    start_date: date,
    end_date: date,
    initial_price: Decimal,
    currency: str,
    payment_due_day: int,
    late_fee_percent_daily: Decimal = Decimal("2.00"),
    adjustment_index: str,
    adjustment_percent: Decimal | None = None,
    adjustment_frequency_months: int,
    deposit_amount: Decimal | None = None,
    guarantee_type: str,
    guarantee_detail: str = "",
    actor: User,
) -> RentalContract:
    """
    Crea un contrato de alquiler.

    Status inicial determinado por start_date:
    - start_date <= today → ACTIVE + property.status = RENTED
    - start_date > today  → SCHEDULED, sin side effect sobre property

    Raises ContractValidationError si adjustment_index=FIXED_PERCENT y
    adjustment_percent es None.
    Raises ContractDateConflict si las fechas solapan con otro contrato
    ACTIVE o SCHEDULED sobre la misma propiedad.
    """
    if adjustment_index == AdjustmentIndex.FIXED_PERCENT and adjustment_percent is None:
        raise ContractValidationError(
            "adjustment_percent es requerido cuando el índice es porcentaje fijo."
        )

    _check_date_overlap(property_id, start_date, end_date)

    status = (
        ContractStatus.ACTIVE
        if start_date <= date.today()
        else ContractStatus.SCHEDULED
    )
    next_adjustment_date = start_date + relativedelta(months=adjustment_frequency_months)

    with transaction.atomic():
        contract = RentalContract(
            property_id=property_id,
            tenant_contact_id=tenant_contact_id,
            owner_contact_id=owner_contact_id,
            deal_id=deal_id,
            start_date=start_date,
            end_date=end_date,
            initial_price=initial_price,
            current_price=initial_price,
            currency=currency,
            payment_due_day=payment_due_day,
            late_fee_percent_daily=late_fee_percent_daily,
            adjustment_index=adjustment_index,
            adjustment_percent=adjustment_percent,
            adjustment_frequency_months=adjustment_frequency_months,
            next_adjustment_date=next_adjustment_date,
            deposit_amount=deposit_amount,
            guarantee_type=guarantee_type,
            guarantee_detail=guarantee_detail,
            status=status,
            created_by=actor,
            updated_by=actor,
        )
        contract.save()

        if status == ContractStatus.ACTIVE:
            update_property_status(
                property=contract.property,
                status=PropertyStatus.RENTED,
                actor=actor,
            )

    return contract


def terminate_contract(*, contract: RentalContract, actor: User) -> RentalContract:
    """
    Rescinde un contrato — opera sobre ACTIVE y SCHEDULED.

    Side effect: solo si estaba ACTIVE → property.status = AVAILABLE.
    Un contrato SCHEDULED nunca activó la propiedad — no hay nada que revertir.

    Raises InvalidContractStatus si el contrato está EXPIRED o TERMINATED.
    """
    if contract.status not in [ContractStatus.ACTIVE, ContractStatus.SCHEDULED]:
        raise InvalidContractStatus(
            f"No se puede rescindir un contrato en estado '{contract.status}'."
        )

    was_active = contract.status == ContractStatus.ACTIVE

    with transaction.atomic():
        contract.status = ContractStatus.TERMINATED
        contract.updated_by = actor
        contract.save(update_fields=["status", "updated_by", "updated_at"])

        if was_active:
            update_property_status(
                property=contract.property,
                status=PropertyStatus.AVAILABLE,
                actor=actor,
            )

    return contract


def expire_contract(*, contract: RentalContract, actor: User) -> RentalContract:
    """
    Vence un contrato — solo ACTIVE.
    Diseñado para ser llamado por la tarea Celery periódica (actor puede ser None).

    Side effect: property.status = AVAILABLE.

    Raises InvalidContractStatus para cualquier otro estado.
    """
    if contract.status != ContractStatus.ACTIVE:
        raise InvalidContractStatus(
            f"No se puede vencer un contrato en estado '{contract.status}'."
        )

    with transaction.atomic():
        contract.status = ContractStatus.EXPIRED
        contract.updated_by = actor
        contract.save(update_fields=["status", "updated_by", "updated_at"])

        update_property_status(
            property=contract.property,
            status=PropertyStatus.AVAILABLE,
            actor=actor,
        )

    return contract


def activate_scheduled_contract(*, contract: RentalContract, actor: User) -> RentalContract:
    """
    Activa un contrato SCHEDULED cuando su start_date llega.
    Diseñado para ser llamado por la tarea Celery periódica (actor puede ser None).

    Side effect: property.status = RENTED.

    Raises InvalidContractStatus para cualquier otro estado.
    """
    if contract.status != ContractStatus.SCHEDULED:
        raise InvalidContractStatus(
            f"No se puede activar un contrato en estado '{contract.status}'."
        )

    with transaction.atomic():
        contract.status = ContractStatus.ACTIVE
        contract.updated_by = actor
        contract.save(update_fields=["status", "updated_by", "updated_at"])

        update_property_status(
            property=contract.property,
            status=PropertyStatus.RENTED,
            actor=actor,
        )

    return contract


def apply_rent_adjustment(
    *,
    contract: RentalContract,
    adjustment_date: date,
    index_value_at_date: Decimal,
    applied_by: User,
) -> RentalContract:
    """
    Aplica un ajuste de alquiler aprobado por un socio.

    index_value_at_date: porcentaje de variación ya calculado.
    Ejemplos: 15.5 = 15.5%, 8.0 = 8.0%.
    En V1 el agente lo ingresa manualmente. En el futuro lo provee
    la integración con la API del gobierno desde integrations/.

    applied_by: no nullable — excepción explícita a la convención general.
    Este registro certifica quién aprobó el ajuste.

    Operación atómica:
    1. Nueva fila en RentAdjustment con trazabilidad completa
    2. contract.current_price = new_price
    3. contract.next_adjustment_date avanza desde el valor anterior
       (el calendario de ajustes no se desplaza por demoras administrativas)

    Raises InvalidContractStatus si el contrato no está ACTIVE.
    """
    if contract.status != ContractStatus.ACTIVE:
        raise InvalidContractStatus(
            f"No se puede aplicar un ajuste a un contrato en estado '{contract.status}'."
        )

    previous_price = contract.current_price
    new_price = (
        previous_price * (Decimal("1") + index_value_at_date / Decimal("100"))
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    new_next_adjustment_date = contract.next_adjustment_date + relativedelta(
        months=contract.adjustment_frequency_months
    )

    with transaction.atomic():
        RentAdjustment.objects.create(
            contract=contract,
            adjustment_date=adjustment_date,
            previous_price=previous_price,
            new_price=new_price,
            index_used=contract.adjustment_index,
            index_value_at_date=index_value_at_date,
            applied_by=applied_by,
        )
        contract.current_price = new_price
        contract.next_adjustment_date = new_next_adjustment_date
        contract.updated_by = applied_by
        contract.save(update_fields=[
            "current_price", "next_adjustment_date", "updated_by", "updated_at"
        ])

    return contract


def update_contract_end_date(
    *,
    contract: RentalContract,
    new_end_date: date,
    actor: User,
) -> RentalContract:
    """
    Actualiza la fecha de fin de un contrato — extensión o acortamiento.

    Opera sobre contratos ACTIVE y SCHEDULED.
    new_end_date debe ser una fecha futura — la delta de complejidad entre
    ACTIVE y SCHEDULED es una sola línea en el guard, sin cambio en la
    lógica de solapamiento.

    Para rescisión con efecto inmediato usar terminate_contract.

    Raises ContractValidationError si new_end_date <= today.
    Raises ContractValidationError si new_end_date <= start_date del contrato.
    Raises ContractDateConflict si las nuevas fechas solapan con otro contrato.
    Raises InvalidContractStatus si el contrato está EXPIRED o TERMINATED.
    """
    if contract.status not in [ContractStatus.ACTIVE, ContractStatus.SCHEDULED]:
        raise InvalidContractStatus(
            f"No se puede modificar la fecha de un contrato en estado '{contract.status}'."
        )

    if new_end_date <= date.today():
        raise ContractValidationError(
            "La nueva fecha de fin debe ser una fecha futura. "
            "Para rescisión inmediata usá terminate_contract."
        )

    if new_end_date <= contract.start_date:
        raise ContractValidationError(
            "La nueva fecha de fin debe ser posterior a la fecha de inicio del contrato."
        )

    _check_date_overlap(
        property_id=contract.property_id,
        start_date=contract.start_date,
        end_date=new_end_date,
        exclude_contract_id=contract.pk,
    )

    contract.end_date = new_end_date
    contract.updated_by = actor
    contract.save(update_fields=["end_date", "updated_by", "updated_at"])

    return contract