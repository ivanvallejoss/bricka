from decimal import Decimal
from uuid import UUID

from django.db import transaction

from apps.users.models import User
from apps.properties.models import ExternalPropertySource, Property, PropertyMedia
from apps.properties.exceptions import PropertyValidationError


def create_property(
    *,
    property_type: str,
    address_line: str,
    city: str,
    province: str,
    area_m2: Decimal,
    neighborhood: str = "",
    bedrooms: int | None = None,
    bathrooms: int | None = None,
    year_built: int | None = None,
    youtube_video_url: str = "",
    features: list[str] | None = None,
    owner_contact_id: UUID | None = None,
    is_external: bool = False,
    agency_name: str = "",
    source_url: str = "",
    agreed_commission_percent: Decimal | None = None,
    actor: User,
) -> Property:
    if is_external and not agency_name:
        raise PropertyValidationError(
            "Una propiedad externa requiere el nombre de la agencia."
        )

    with transaction.atomic():
        property = Property(
            property_type=property_type,
            address_line=address_line,
            city=city,
            province=province,
            area_m2=area_m2,
            neighborhood=neighborhood,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            year_built=year_built,
            youtube_video_url=youtube_video_url,
            features=features or [],
            owner_contact_id=owner_contact_id,
            is_external=is_external,
            created_by=actor,
            updated_by=actor,
        )
        property.save()

        if is_external:
            ExternalPropertySource.objects.create(
                property=property,
                agency_name=agency_name,
                source_url=source_url,
                agreed_commission_percent=agreed_commission_percent,
            )

    return property


def update_property(
    *,
    property: Property,
    address_line: str | None = None,
    city: str | None = None,
    province: str | None = None,
    neighborhood: str | None = None,
    area_m2: Decimal | None = None,
    bedrooms: int | None = None,
    bathrooms: int | None = None,
    year_built: int | None = None,
    youtube_video_url: str | None = None,
    features: list[str] | None = None,
    owner_contact_id: UUID | None = None,
    actor: User,
) -> Property:
    update_fields = ["updated_by", "updated_at"]

    if address_line is not None:
        property.address_line = address_line
        update_fields.append("address_line")

    if city is not None:
        property.city = city
        update_fields.append("city")

    if province is not None:
        property.province = province
        update_fields.append("province")

    if neighborhood is not None:
        property.neighborhood = neighborhood
        update_fields.append("neighborhood")

    if area_m2 is not None:
        property.area_m2 = area_m2
        update_fields.append("area_m2")

    if bedrooms is not None:
        property.bedrooms = bedrooms
        update_fields.append("bedrooms")

    if bathrooms is not None:
        property.bathrooms = bathrooms
        update_fields.append("bathrooms")

    if year_built is not None:
        property.year_built = year_built
        update_fields.append("year_built")

    if youtube_video_url is not None:
        property.youtube_video_url = youtube_video_url
        update_fields.append("youtube_video_url")

    if features is not None:
        property.features = features
        update_fields.append("features")

    if owner_contact_id is not None:
        property.owner_contact_id = owner_contact_id
        update_fields.append("owner_contact_id")
        
    property.updated_by = actor
    property.save(update_fields=update_fields)

    return property


def update_property_status(*, property: Property, status: str, actor: User) -> Property:
    """
    Actualiza el status de una propiedad.
    Punto de entrada para transiciones disparadas por el sistema
    (ej: close_deal WON → RENTED / SOLD).

    Separada de update_property para dar intención explícita
    en los call sites — quien lee close_deal sabe exactamente
    qué está pasando sin parsear una firma genérica.
    """
    property.status = status
    property.updated_by = actor
    property.save(update_fields=["status", "updated_by", "updated_at"])
    return property


def archive_property(*, property: Property, actor: User) -> Property:
    property.soft_delete(actor=actor)
    return property


def upload_property_media(
    *,
    property: Property,
    r2_key: str,
    mime_type: str,
    order: int = 0,
    actor: User,
) -> PropertyMedia:
    has_cover = PropertyMedia.objects.filter(
        property_id=property.pk,
        is_cover=True,
    ).exists()

    media = PropertyMedia(
        property=property,
        r2_key=r2_key,
        mime_type=mime_type,
        order=order,
        is_cover=not has_cover,
        created_by=actor,
    )
    media.save()
    return media


def set_cover_media(*, media: PropertyMedia) -> PropertyMedia:
    with transaction.atomic():
        PropertyMedia.objects.filter(
            property_id=media.property_id,
            is_cover=True,
        ).exclude(pk=media.pk).update(is_cover=False)

        media.is_cover = True
        media.save(update_fields=["is_cover"])

    return media


def delete_property_media(*, media: PropertyMedia) -> None:
    """
    Hard delete del registro en DB.
    PRECONDICIÓN: el caller ya eliminó el archivo de R2 exitosamente.
    El orden de operaciones (R2 primero, DB después) es responsabilidad
    de la view — este service asume que R2 ya fue limpiado.
    """
    media.delete()