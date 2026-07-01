from dataclasses import dataclass
from uuid import UUID

from django.db.models import Exists, OuterRef, QuerySet, Prefetch

from apps.listings.choices import ListingStatus, PublicationStatus
from apps.listings.models import Listing, ListingPriceHistory, ListingPublication


@dataclass
class ListingFilters:
    status: str | None = None
    operation_type: str | None = None
    currency: str | None = None


def published_listing_subquery(operation_type: str | None = None) -> Exists:
    """
    Devuelve un Exists subquery para anotar o filtrar querysets de Property.
    No ejecuta queries — construye el subquery para ser inyectado
    en un annotate() o filter() externo.

    Uso en anotaciones (properties/selectors.py):
        Property.objects.annotate(has_sale=published_listing_subquery("sale"))

    Uso en filtros:
        Property.objects.filter(published_listing_subquery("rent"))
    """
    qs = Listing.objects.filter(
        property=OuterRef("pk"),
        status=ListingStatus.PUBLISHED,
        deleted_at__isnull=True,
    )
    if operation_type is not None:
        qs = qs.filter(operation_type=operation_type)
    return Exists(qs)


def get_listing_detail(listing_id: UUID) -> Listing:
    try:
        return Listing.objects.select_related("property").get(pk=listing_id)
    except Listing.DoesNotExist:
        raise


def get_listing_list(
    filters: ListingFilters | None = None,
) -> QuerySet[Listing]:
    qs = Listing.objects.select_related("property")

    if filters is None:
        return qs

    if filters.status is not None:
        qs = qs.filter(status=filters.status)

    if filters.operation_type is not None:
        qs = qs.filter(operation_type=filters.operation_type)

    if filters.currency is not None:
        qs = qs.filter(currency=filters.currency)

    return qs


def get_listings_for_property(property_id: UUID) -> QuerySet[Listing]:
    return Listing.objects.filter(
        property_id=property_id,
        deleted_at__isnull=True,
    ).order_by("operation_type")


def get_price_history_for_listing(listing_id: UUID) -> QuerySet[ListingPriceHistory]:
    return ListingPriceHistory.objects.filter(
        listing_id=listing_id,
    ).select_related("created_by")


def get_listings_for_reconciliation(
    property_id: UUID,
    *,
    statuses: list[str],
    operation_types: list[str] | None = None,
) -> QuerySet[Listing]:
    """
    Listings no borrados de una propiedad, filtrados por status y opcionalmente
    por operation_type.

    Lectura para el módulo de coordinación (operations): el orquestador de
    estado cruzado la usa para resolver qué listings reconciliar ante una
    transición de Property.status. No decide la política —qué status se filtra
    para qué transición eso vive en operations; este selector solo materializa
    el set pedido.
    """
    qs = Listing.objects.filter(
        property_id=property_id,
        status__in=statuses,
        deleted_at__isnull=True,
    )
    if operation_types is not None:
        qs = qs.filter(operation_type__in=operation_types)
    return qs.order_by("operation_type")


def get_active_publications_for_listings(
    listing_ids: list[UUID],
) -> QuerySet[ListingPublication]:
    """
    Publicaciones en PUBLISHED de un conjunto de listings.

    El módulo de coordinación la usa para detectar publicaciones externas que
    quedaron vivas tras cerrar o pausar sus listings — el set a dar de baja
    manualmente en V1 (todavía sin API de canales).
    """
    return ListingPublication.objects.filter(
        listing_id__in=listing_ids,
        status=PublicationStatus.PUBLISHED,
    ).select_related("listing")


def get_pending_publications() -> QuerySet[ListingPublication]:
    return (
        ListingPublication.objects
        .filter(status=PublicationStatus.PENDING)
        .select_related("listing__property")
    )

def active_listings_prefetch() -> Prefetch:
    """
    Prefetch de listings publicados para anotar querysets de Property.
    Exportado como building block — properties/selectors.py lo importa.
    """
    return Prefetch(
        "listings",
        queryset=Listing.objects.filter(
            status__in=[ListingStatus.PUBLISHED, ListingStatus.PAUSED],
            deleted_at__isnull=True,
        ).order_by("operation_type"),
        to_attr="active_listings",
    )


def all_listings_prefetch() -> Prefetch:
    """
    Prefetch de TODOS los listings (cualquier status, no borrados) para
    mostrar precio en el listado sin filtrar por publicado/pausado.
    """
    return Prefetch(
        "listings",
        queryset=Listing.objects.filter(
            deleted_at__isnull=True,
        ).order_by("operation_type"),
        to_attr="price_listings",
    )