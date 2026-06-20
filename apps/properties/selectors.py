from dataclasses import dataclass
from uuid import UUID

from django.db.models import Prefetch, QuerySet, Q

from apps.properties.models import Property, PropertyMedia

from apps.listings.selectors import published_listing_subquery, active_listings_prefetch

from apps.contracts.selectors import active_contracts_prefetch

@dataclass
class PropertyFilters:
    status: list[str] | None = None
    operation_type: str | None = None
    property_type: str | None = None
    is_external: bool | None = None
    search: str | None = None


def get_property_list(
    filters: PropertyFilters | None = None,
) -> QuerySet[Property]:
    qs = Property.objects.prefetch_related(
        Prefetch(
            "media",
            queryset=PropertyMedia.objects.filter(is_cover=True),
            to_attr="cover_media_list",
        ),
        active_listings_prefetch(),
        active_contracts_prefetch(),
    ).annotate(
        has_sale_listing=published_listing_subquery("sale"),
        has_rent_listing=published_listing_subquery("rent"),
    )

    if filters is None:
        return qs

    if filters.status is not None:
        qs = qs.filter(status__in=filters.status)

    if filters.operation_type is not None:
        qs = qs.filter(
            published_listing_subquery(filters.operation_type)
        )

    if filters.property_type is not None:
        qs = qs.filter(property_type=filters.property_type)

    if filters.is_external is not None:
        qs = qs.filter(is_external=filters.is_external)

    if filters.search:
        qs = qs.filter(
            Q(title__icontains=filters.search) |
            Q(address_line__icontains=filters.search) |
            Q(neighborhood__icontains=filters.search) |
            Q(city__icontains=filters.search)
        )

    return qs


def get_property_preview(property_id: UUID) -> Property:
    """
    Carga mínima para el slide-over. Solo foto cover y campos base.
    La view que llama este selector es responsable de llamar
    get_listings_for_property() por separado si necesita precios activos.
    """
    try:
        return (
            Property.objects
            .prefetch_related(
                Prefetch(
                    "media",
                    queryset=PropertyMedia.objects.filter(is_cover=True),
                    to_attr="cover_media_list",
                ),
            )
            .annotate(
                has_sale_listing=published_listing_subquery("sale"),
                has_rent_listing=published_listing_subquery("rent"),
            )
            .get(pk=property_id)
        )
    except Property.DoesNotExist:
        raise


def get_property_detail(property_id: UUID) -> Property:
    """
    Carga completa para la vista de página entera.
    No incluye listings — la view llama get_listings_for_property() por separado.
    Ver nota de diseño abajo.
    """
    try:
        return (
            Property.objects
            .select_related("owner_contact")
            .prefetch_related(
                Prefetch(
                    "media",
                    queryset=PropertyMedia.objects.order_by("order"),
                ),
            )
            .annotate(
                has_sale_listing=published_listing_subquery("sale"),
                has_rent_listing=published_listing_subquery("rent"),
            )
            .get(pk=property_id)
        )
    except Property.DoesNotExist:
        raise


def get_property_media(property_id: UUID) -> QuerySet[PropertyMedia]:
    if not Property.objects.filter(pk=property_id).exists():
        raise Property.DoesNotExist
    return PropertyMedia.objects.filter(property_id=property_id)