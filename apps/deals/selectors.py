from dataclasses import dataclass
from datetime import date
from uuid import UUID

from django.db.models import QuerySet

from .models import Deal


def get_open_deals_for_contact(contact_id: UUID) -> QuerySet:
    """
    Retorna deals activos (sin outcome) asociados a un contacto.
    Usado por contacts/services.py para validar archivado.
    Un deal sin outcome es un deal en curso — WON, LOST y CANCELLED
    son los tres estados de cierre posibles.
    """
    return Deal.objects.filter(
        client_contact_id=contact_id,
        outcome="",
    )


def get_open_deals_for_listing(listing_id: UUID) -> QuerySet:
    """
    Retorna deals activos (sin outcome) asociados a un listing.
    Disponible como punto de entrada cross-app para listings/.
    Ejemplo de uso futuro: bloquear archivado de listing con deals activos.
    """
    return Deal.objects.filter(
        listing_id=listing_id,
        outcome="",
    )


@dataclass
class DealFilters:
    deal_type: str | None = None
    outcome: str | None = None
    agent_id: UUID | None = None
    client_contact_id: UUID | None = None
    listing_id: UUID | None = None
    is_open: bool | None = None               # True → outcome="", False → outcome != ""
    expected_close_before: date | None = None


def get_deal_list(filters: DealFilters | None = None) -> QuerySet:
    """
    Retorna deals no archivados con relaciones base cargadas.
    El manager default excluye soft-deleted.
    """
    qs = Deal.objects.select_related(
        "client_contact",
        "agent",
        "listing",
    ).all()

    if filters is None:
        return qs

    if filters.deal_type is not None:
        qs = qs.filter(deal_type=filters.deal_type)

    if filters.outcome is not None:
        qs = qs.filter(outcome=filters.outcome)

    if filters.agent_id is not None:
        qs = qs.filter(agent_id=filters.agent_id)

    if filters.client_contact_id is not None:
        qs = qs.filter(client_contact_id=filters.client_contact_id)

    if filters.listing_id is not None:
        qs = qs.filter(listing_id=filters.listing_id)

    if filters.is_open is not None:
        if filters.is_open:
            qs = qs.filter(outcome="")
        else:
            qs = qs.exclude(outcome="")

    if filters.expected_close_before is not None:
        qs = qs.filter(expected_close_date__lte=filters.expected_close_before)

    return qs


def get_deal_detail(deal_id: UUID) -> Deal:
    """
    Retorna un deal con relaciones completas para vista de detalle.
    listing__property incluido para habilitar acceso al status de la
    propiedad sin queries adicionales en templates.
    Raises Deal.DoesNotExist si no existe o está soft-deleted.
    """
    return (
        Deal.objects.select_related(
            "client_contact",
            "agent",
            "listing",
            "listing__property",
        )
        .get(pk=deal_id)
    )