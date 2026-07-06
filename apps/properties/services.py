from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.contrib.gis.geos import Point

from apps.common.sentinels import UNSET
from apps.users.models import User
from apps.properties.models import ExternalPropertySource, Property, PropertyMedia, Feature
from apps.properties.exceptions import PropertyValidationError


def _resolve_features(slugs: list[str]) -> list[Feature]:
    """
    Traduce slugs a filas de Feature con validación estricta.
    Rechazo explícito, nunca filtrado silencioso.
    Slug inactivo rechaza en escritura nueva — las asignaciones
    históricas no se tocan (viven en el M2M, no pasan por acá).
    """
    unique = set(slugs)
    if not unique:
        return []

    rows = {f.slug: f for f in Feature.objects.filter(slug__in=unique)}
    unknown = sorted(unique - rows.keys())
    inactive = sorted(s for s in unique & rows.keys() if not rows[s].is_active)

    if unknown or inactive:
        parts = []
        if unknown:
            parts.append(f"desconocidas: {', '.join(unknown)}")
        if inactive:
            parts.append(f"inactivas: {', '.join(inactive)}")
        raise PropertyValidationError(f"Features inválidas — {'; '.join(parts)}.")

    return list(rows.values())


def create_property(
    *,
    property_type: str,
    address_line: str,
    city: str,
    province: str,
    title: str = "",
    description: str = "",
    neighborhood: str = "",
    location: Point | None = None,
    area_m2: Decimal | None = None,
    bedrooms: int | None = None,
    bathrooms: int | None = None,
    parking_spaces: int | None = None,
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
    """
    Umbral de creación = operable, no publicable (ver docs/decisions):
    lo obligatorio es que la propiedad sea identificable y asociable.
    Las exigencias de completitud viven en el gate de publicación.
    """
    if is_external and not agency_name:
        raise PropertyValidationError(
            "Una propiedad externa requiere el nombre de la agencia."
        )

    feature_rows = _resolve_features(features) if features else []

    with transaction.atomic():
        property = Property(
            property_type=property_type,
            address_line=address_line,
            city=city,
            province=province,
            title=title,
            description=description,
            neighborhood=neighborhood,
            location=location,
            area_m2=area_m2,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            parking_spaces=parking_spaces,
            year_built=year_built,
            youtube_video_url=youtube_video_url,
            owner_contact_id=owner_contact_id,
            is_external=is_external,
            created_by=actor,
            updated_by=actor,
        )
        property.save()

        if feature_rows:
            property.features.set(feature_rows)

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
    title: str = UNSET,
    description: str = UNSET,
    address_line: str = UNSET,
    city: str = UNSET,
    province: str = UNSET,
    neighborhood: str = UNSET,
    location: Point | None = UNSET,
    area_m2: Decimal | None = UNSET,
    bedrooms: int | None = UNSET,
    bathrooms: int | None = UNSET,
    parking_spaces: int | None = UNSET,
    year_built: int | None = UNSET,
    youtube_video_url: str = UNSET,
    features: list[str] = UNSET,
    owner_contact_id: UUID | None = UNSET,
    actor: User,
) -> Property:
    """
    Actualización parcial con sentinela:
      - UNSET (default) → el campo no se toca.
      - None / "" / [] → blanquear (semántica de reemplazo desde el form).
      - valor → set.
    features: UNSET = no tocar, [] = vaciar, lista de slugs = reemplazo total.
    is_external NO es editable — la invariante 1:1 con ExternalPropertySource
    se protege acá por omisión deliberada.
    """
    field_values = {
        "title": title,
        "description": description,
        "address_line": address_line,
        "city": city,
        "province": province,
        "neighborhood": neighborhood,
        "location": location,
        "area_m2": area_m2,
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "parking_spaces": parking_spaces,
        "year_built": year_built,
        "youtube_video_url": youtube_video_url,
        "owner_contact_id": owner_contact_id,
    }

    update_fields = ["updated_by", "updated_at"]
    for field, value in field_values.items():
        if value is not UNSET:
            setattr(property, field, value)
            update_fields.append(field)

    feature_rows: list[Feature] | None = None
    if features is not UNSET:
        feature_rows = _resolve_features(features)

    property.updated_by = actor

    with transaction.atomic():
        property.save(update_fields=update_fields)
        if feature_rows is not None:
            property.features.set(feature_rows)

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