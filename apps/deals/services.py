from datetime import date
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.common.utils import UNSET
from apps.properties.choices import PropertyStatus
from apps.operations.services import settle_won_sale, transition_property_status

from .choices import DealOutcome, DealType
from .exceptions import DealAlreadyClosed, DealValidationError
from .models import Deal

User = get_user_model()


def create_deal(
    *,
    deal_type: str,
    client_contact_id: UUID,
    listing_id: UUID | None = None,
    external_property_notes: str = "",
    agent_id: UUID | None = None,
    expected_close_date: date | None = None,
    notes: str = "",
    actor: User,
) -> Deal:
    """
    Crea un deal.

    INVARIANTE: listing_id o external_property_notes debe estar presente.
    Validado aquí antes de llegar a la DB — da un error claro
    en lugar de una IntegrityError de constraint.
    """
    if not listing_id and not external_property_notes:
        raise DealValidationError(
            "Un deal requiere un listing o una descripción de propiedad externa."
        )

    deal = Deal(
        deal_type=deal_type,
        client_contact_id=client_contact_id,
        listing_id=listing_id,
        external_property_notes=external_property_notes,
        agent_id=agent_id,
        expected_close_date=expected_close_date,
        notes=notes,
        created_by=actor,
        updated_by=actor,
    )
    deal.save()
    return deal


def update_deal(
    *,
    deal: Deal,
    agent_id=UNSET,
    expected_close_date=UNSET,
    notes=UNSET,
    actor: User,
) -> Deal:
    """
    Actualización parcial de un deal.

    Usa UNSET para distinguir "no enviado" de None.
    agent_id=None         → desasigna el agente explícitamente.
    expected_close_date=None → elimina la fecha estimada de cierre.
    """
    update_fields = ["updated_by", "updated_at"]

    if agent_id is not UNSET:
        deal.agent_id = agent_id
        update_fields.append("agent_id")

    if expected_close_date is not UNSET:
        deal.expected_close_date = expected_close_date
        update_fields.append("expected_close_date")

    if notes is not UNSET:
        deal.notes = notes
        update_fields.append("notes")

    deal.updated_by = actor
    deal.save(update_fields=update_fields)
    return deal


def close_deal(
    *,
    deal: Deal,
    outcome: str,
    actor: User,
) -> Deal:
    """
    Side effects cuando outcome=WON y deal.listing_id no es null:
      RENT → Property.status = RENTED (vía orquestador: cierra el listing de
             alquiler; deja el de venta si existe).
      SALE → settle_won_sale: cierra el listing de venta siempre, y transiciona
             a SOLD SOLO si la propiedad estaba AVAILABLE. Si está RENTED, la
             ocupación gana y el estado no se pisa (regla de precedencia).

    La coordinación cross-entity (listings, estado, surface) vive en operations;
    este service no toca listings ni Property.status directamente.

    Sin side effect para propiedades ajenas (deal.listing_id is None).
    """
    if deal.outcome:
        raise DealAlreadyClosed("El deal ya fue cerrado.")

    with transaction.atomic():
        deal.outcome = outcome
        deal.closed_at = timezone.now()
        deal.updated_by = actor
        deal.save(update_fields=["outcome", "closed_at", "updated_by", "updated_at"])

        if outcome == DealOutcome.WON and deal.listing_id is not None:
            prop = deal.listing.property
            if deal.deal_type == DealType.RENT:
                transition_property_status(
                    property=prop,
                    new_status=PropertyStatus.RENTED,
                    actor=actor,
                )
            else:  # SALE
                settle_won_sale(property=prop, actor=actor)

    return deal


def archive_deal(*, deal: Deal, actor: User) -> Deal:
    """
    Archiva un deal (soft delete).
    Opera sobre deals abiertos y cerrados.
    Uso previsto: corrección de error, no limpieza de historial.
    El historial de deals cerrados permanece visible por defecto.
    """
    deal.soft_delete(actor=actor)
    return deal