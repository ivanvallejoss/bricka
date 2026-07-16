from decimal import Decimal

from django.utils import timezone
from django.db import transaction

from apps.users.models import User
from .choices import ListingStatus, OperationType, PublicationStatus
from .exceptions import ListingValidationError, ListingPublicationRequirementsError
from .models import Listing, ListingPriceHistory, ListingPublication
from apps.properties.models import Property


# Requisitos del gate de publicación. Fuente única de estos números: la UI
# los importa desde acá (contadores, checklist) — no se duplican en templates.
MIN_PHOTOS_TO_PUBLISH = 5
MIN_DESCRIPTION_LENGTH = 150


def create_listing(
    *,
    property: Property,
    operation_type: str,
    price: Decimal,
    currency: str,
    period: str,
    price_min_acceptable: Decimal | None = None,
    available_from=None,
    available_until=None,
    actor: User,
) -> Listing:
    active_exists = Listing.objects.filter(
        property=property,
        operation_type=operation_type,
        status__in=[ListingStatus.PUBLISHED, ListingStatus.PAUSED],
        deleted_at__isnull=True,
    ).exists()

    if active_exists:
        raise ListingValidationError(
            f"Ya existe un listing activo de tipo "
            f"'{operation_type}' para esta propiedad."
        )

    with transaction.atomic():
        listing = Listing(
            property=property,
            operation_type=operation_type,
            price=price,
            currency=currency,
            period=period,
            price_min_acceptable=price_min_acceptable,
            available_from=available_from,
            available_until=available_until,
            status=ListingStatus.DRAFT,
            created_by=actor,
            updated_by=actor,
        )
        listing.save()

        ListingPriceHistory.objects.create(
            listing=listing,
            price=price,
            currency=currency,
            created_by=actor,
        )

    return listing


def update_listing_price(
    *,
    listing: Listing,
    price: Decimal,
    actor: User,
) -> Listing:
    with transaction.atomic():
        listing.price = price
        listing.updated_by = actor
        listing.save(update_fields=["price", "updated_by", "updated_at"])

        ListingPriceHistory.objects.create(
            listing=listing,
            price=price,
            currency=listing.currency,
            created_by=actor,
        )

    return listing


def _publication_requirements_missing(property: Property) -> list[str]:
    """
    Gate de publicación (contrato: Decisión 3 de la vertical properties;
    la implementación vive acá porque publicar es un acto del listing).
    Invariante: nada incompleto llega a estado público.

    v2 (S3a): descripción ≥ MIN_DESCRIPTION_LENGTH caracteres (post-strip)
    + ≥ MIN_PHOTOS_TO_PUBLISH fotos. Las constantes se exportan y la UI las
    importa (contadores, checklist) — una sola fuente de números. Los códigos
    ('description' / 'photos') no cambian: el contrato con la UI se mantiene.
    - area_m2 queda FUERA a propósito: un gate uniforme bloquearía
      publicar una cochera sin m². Extensión futura por property_type.
    - price no se chequea: create_listing lo exige y el modelo es NOT NULL.
    """
    missing = []
    if len(property.description.strip()) < MIN_DESCRIPTION_LENGTH:
        missing.append("description")
    if property.media.count() < MIN_PHOTOS_TO_PUBLISH:
        missing.append("photos")
    return missing


def update_listing_status(
    *,
    listing: Listing,
    status: str,
    actor: User,
) -> Listing:
    if status == ListingStatus.PUBLISHED:
        active_exists = Listing.objects.filter(
            property=listing.property,
            operation_type=listing.operation_type,
            status__in=[ListingStatus.PUBLISHED, ListingStatus.PAUSED],
            deleted_at__isnull=True,
        ).exclude(pk=listing.pk).exists()

        if active_exists:
            raise ListingValidationError(
                f"Ya existe un listing activo de tipo "
                f"'{listing.operation_type}' para esta propiedad."
            )
            
        missing = _publication_requirements_missing(listing.property)
        if missing:
            raise ListingPublicationRequirementsError(missing)

    listing.status = status
    listing.updated_by = actor
    listing.save(update_fields=["status", "updated_by", "updated_at"])

    return listing


def archive_listing(*, listing: Listing, actor: User) -> Listing:
    listing.soft_delete(actor=actor)
    return listing

def create_listing_publication(
    *,
    listing: Listing,
    channel: str,
    actor: User,
) -> ListingPublication:
    if ListingPublication.objects.filter(
        listing=listing,
        channel=channel,
    ).exists():
        raise ListingValidationError(
            f"Ya existe una publicación para este listing en '{channel}'."
        )

    publication = ListingPublication(
        listing=listing,
        channel=channel,
        status=PublicationStatus.PENDING,
        created_by=actor,
        updated_by=actor,
    )
    publication.save()
    return publication


def update_publication_status(
    *,
    publication: ListingPublication,
    status: str,
    external_id: str = "",
    metadata: dict | None = None,
    actor: User | None = None,
) -> ListingPublication:
    publication.status = status
    publication.updated_by = actor
    publication.last_synced_at = timezone.now()

    if external_id:
        publication.external_id = external_id

    if metadata is not None:
        publication.metadata = metadata

    if status == PublicationStatus.PUBLISHED:
        publication.published_at = timezone.now()

    publication.save(update_fields=[
        "status",
        "external_id",
        "metadata",
        "published_at",
        "last_synced_at",
        "updated_by",
        "updated_at",
    ])
    return publication