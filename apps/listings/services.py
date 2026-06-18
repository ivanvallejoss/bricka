from decimal import Decimal

from django.utils import timezone
from django.db import transaction

from apps.users.models import User
from apps.listings.choices import ListingStatus, OperationType, PublicationStatus
from apps.listings.exceptions import ListingValidationError
from apps.listings.models import Listing, ListingPriceHistory, ListingPublication
from apps.properties.models import Property


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