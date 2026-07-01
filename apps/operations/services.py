from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import transaction

from .exceptions import InvalidPropertyTransition

from apps.listings.choices import ListingStatus, OperationType
from apps.listings.selectors import (
    get_active_publications_for_listings,
    get_listings_for_reconciliation,
)
from apps.listings.services import update_listing_status

from apps.properties.choices import PropertyStatus
from apps.properties.services import update_property_status, update_property

if TYPE_CHECKING:
    from apps.listings.models import Listing
    from apps.properties.models import Property

User = get_user_model()
logger = logging.getLogger(__name__)


# Listings "vivos en superficie propia": retienen el slot del constraint
# unique_active_listing_per_operation. Son los que se cierran al vender/alquilar.
_ACTIVE_LISTING_STATUSES = [ListingStatus.PUBLISHED, ListingStatus.PAUSED]

# operation_types de alquiler. RENTED cierra solo estos; el de venta sigue vivo.
_RENT_OPERATION_TYPES = [OperationType.RENT, OperationType.TEMPORARY_RENT]


def transition_property_status(
    *,
    property: Property,
    new_status: str,
    actor: User | None,
) -> Property:
    """
    Único punto de entrada para cambiar Property.status.

    Escribe el estado (delegando en properties.services.update_property_status)
    y reconcilia en cascada los listings de la propiedad, más el surface de las
    publicaciones externas a dar de baja, según la tabla de reconciliación del
    diseño (docs/decisions/design). Todos los call-sites que hoy llaman
    update_property_status suelto deben pasar por acá.

    La cascada es asimétrica: bajar (cerrar/pausar) es automático; subir
    (republicar en un canal externo) es manual — consume un slot finito y una
    llamada de API, decisión del agente. La landing propia, gratis, sí vuelve
    sola porque su visibilidad es Listing.status == PUBLISHED.

    actor=None es válido: convención "sistema" para tareas sin usuario
    (scheduler Celery, futuro).

    Se envuelve en su propio transaction.atomic(). Cuando el caller ya abrió una
    transacción (close_deal, services de contrato), este bloque anida como
    savepoint — la coherencia es transaccional sin trabajo extra. Cuando lo
    llame un service que no pre-envuelve (withdraw/restore/remandate, paso 4),
    el atomic propio garantiza la atomicidad igual.

    NOTA: todavía no incluye el guard que bloquea el deslizamiento silencioso
    desde SOLD (paso 3 del orden de implementación). Hasta entonces cualquier
    transición saliente de SOLD se ejecuta sin resistencia.
    """
    with transaction.atomic():
        update_property_status(property=property, status=new_status, actor=actor)
        _reconcile_listings(property=property, new_status=new_status, actor=actor)

    return property


def withdraw_property(*, property: Property, actor: User | None) -> Property:
    """
    Retira una propiedad del mercado: AVAILABLE → UNAVAILABLE.

    Retiro reversible (refacción, decisión del dueño). Pausa los listings
    publicados vía el orquestador — salen de la landing pero retienen el slot.
    Se revierte con restore_property. Cierra el gap #6: UNAVAILABLE era el único
    estado sin service de transición.
    """
    if property.status != PropertyStatus.AVAILABLE:
        raise InvalidPropertyTransition(
            f"Solo se puede retirar del mercado una propiedad AVAILABLE "
            f"(estado actual: {property.status})."
        )
    return transition_property_status(
        property=property,
        new_status=PropertyStatus.UNAVAILABLE,
        actor=actor,
    )


def restore_property(*, property: Property, actor: User | None) -> Property:
    """
    Reactiva una propiedad retirada: UNAVAILABLE → AVAILABLE.

    Despausa los listings pausados vía el orquestador (vuelven a la landing).
    Inversa de withdraw_property.
    """
    if property.status != PropertyStatus.UNAVAILABLE:
        raise InvalidPropertyTransition(
            f"Solo se puede reactivar una propiedad UNAVAILABLE "
            f"(estado actual: {property.status})."
        )
    return transition_property_status(
        property=property,
        new_status=PropertyStatus.AVAILABLE,
        actor=actor,
    )


def remandate_property(
    *,
    property: Property,
    new_owner_contact_id: UUID,
    actor: User | None,
) -> Property:
    """
    Re-mandato tras una venta: SOLD → AVAILABLE, con nuevo dueño.

    Es la única salida sancionada de SOLD (Decisión 3): la propiedad vuelve al
    mercado bajo el comprador y queda vendible de nuevo. Actualiza owner_contact
    y reactiva vía el orquestador:
      - alquiler (PAUSED) → PUBLISHED: el inversor sigue alquilando, vuelve a la
        landing;
      - venta (CLOSED) → queda quieto: representa una venta ya concretada; volver
        a vender es crear un listing de venta fresco, no resucitar el viejo.

    Republicar en canales externos sigue siendo manual (asimetría de slots).
    """
    if property.status != PropertyStatus.SOLD:
        raise InvalidPropertyTransition(
            f"Solo se puede re-mandar una propiedad SOLD "
            f"(estado actual: {property.status})."
        )
    with transaction.atomic():
        update_property(
            property=property,
            owner_contact_id=new_owner_contact_id,
            actor=actor,
        )
        transition_property_status(
            property=property,
            new_status=PropertyStatus.AVAILABLE,
            actor=actor,
        )
    return property


def _reconcile_listings(
    *,
    property: Property,
    new_status: str,
    actor: User | None,
) -> None:
    """
    Aplica la fila de la tabla de reconciliación que corresponde a new_status.

    La política (qué estado de Property mapea a qué acción sobre listings) vive
    acá. La lectura del set sale de listings/selectors; la mutación pasa por
    listings/services (update_listing_status), nunca por un bulk .update() —
    AuditedQuerySet lo bloquea a propósito para no saltear el audit log.
    """
    if new_status == PropertyStatus.SOLD:
        # La venta se concretó: cerrar los listings de venta (no se puede seguir
        # vendiendo lo ya vendido). El alquiler NO se cierra: si el nuevo dueño
        # sigue el mandato, la unidad sigue alquilable — dato de negocio que la
        # función no conoce y solo sabe el agente. Se pausa (sale de la landing,
        # retiene el slot) y queda como decisión humana explícita: reactivar
        # (caso inversor) o cerrar deliberadamente.
        closed = _close_listings(
            property_id=property.pk,
            actor=actor,
            operation_types=[OperationType.SALE],
        )
        paused = _pause_listings(
            property_id=property.pk,
            actor=actor,
            operation_types=_RENT_OPERATION_TYPES,
        )
        _surface_external_publications(closed + paused)

    elif new_status == PropertyStatus.RENTED:
        # Cerrar solo los de alquiler; el de venta sigue vivo (published).
        closed = _close_listings(
            property_id=property.pk,
            actor=actor,
            operation_types=_RENT_OPERATION_TYPES,
        )
        _surface_external_publications(closed)

    elif new_status == PropertyStatus.UNAVAILABLE:
        # Retiro reversible: pausar los publicados (retiene el slot).
        paused = _pause_listings(property_id=property.pk, actor=actor)
        _surface_external_publications(paused)

    elif new_status == PropertyStatus.AVAILABLE:
        # Volver al mercado: despausar los PAUSED. Los CLOSED quedan quietos
        # (post-venta el agente re-lista fresco). Sin surface: republicar en
        # un canal externo es manual.
        _unpause_listings(property_id=property.pk, actor=actor)


def _close_listings(
    *,
    property_id: UUID,
    actor: User | None,
    operation_types: list[str] | None = None,
) -> list[Listing]:
    """Cierra los listings activos (PUBLISHED/PAUSED). Devuelve los cerrados."""
    listings = list(
        get_listings_for_reconciliation(
            property_id,
            statuses=_ACTIVE_LISTING_STATUSES,
            operation_types=operation_types,
        )
    )
    for listing in listings:
        update_listing_status(
            listing=listing,
            status=ListingStatus.CLOSED,
            actor=actor,
        )
    return listings


def _pause_listings(
    *,
    property_id: UUID,
    actor: User | None,
    operation_types: list[str] | None = None,
) -> list[Listing]:
    """Pausa los listings publicados (PUBLISHED → PAUSED). Devuelve los pausados."""
    listings = list(
        get_listings_for_reconciliation(
            property_id,
            statuses=[ListingStatus.PUBLISHED],
            operation_types=operation_types,
        )
    )
    for listing in listings:
        update_listing_status(
            listing=listing,
            status=ListingStatus.PAUSED,
            actor=actor,
        )
    return listings


def _unpause_listings(*, property_id: UUID, actor: User | None) -> list[Listing]:
    """Despausa los listings pausados (PAUSED → PUBLISHED). Devuelve los reactivados."""
    listings = list(
        get_listings_for_reconciliation(
            property_id,
            statuses=[ListingStatus.PAUSED],
        )
    )
    for listing in listings:
        update_listing_status(
            listing=listing,
            status=ListingStatus.PUBLISHED,
            actor=actor,
        )
    return listings


def _surface_external_publications(listings: list[Listing]) -> None:
    """
    Detecta publicaciones externas que quedaron vivas (PUBLISHED) tras cerrar o
    pausar sus listings, y las *reporta* — no las baja.

    V1 = "avisar, no actuar". Sin la API del canal, voltear la fila a
    unpublished sin bajar el aviso real sería mentir. El rol de hoy es surface:
    dejar registro de que hay una baja manual pendiente.

    PENDIENTE (paso 6, integración de canales): reemplazar este logging por la
    baja automática vía la API del canal, y/o exponerlo en la UI como tarea
    pendiente para el agente. Cuando eso entre, esta función es el punto único a
    cambiar.
    """
    if not listings:
        return

    publications = get_active_publications_for_listings(
        [listing.pk for listing in listings]
    )
    for publication in publications:
        logger.warning(
            "listing_publication_requires_manual_takedown",
            extra={
                "listing_id": str(publication.listing_id),
                "publication_id": str(publication.pk),
                "channel": publication.channel,
                "external_id": publication.external_id,
            },
        )