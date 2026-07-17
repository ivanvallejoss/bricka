from decimal import Decimal
from uuid import UUID
from pathlib import PurePosixPath

from django.db import transaction
from django.contrib.gis.geos import Point

from apps.common.sentinels import UNSET
from apps.users.models import User
from apps.properties.models import ExternalPropertySource, Property, PropertyMedia, Feature
from apps.properties.exceptions import PropertyValidationError


# Límites de media de una propiedad. Dominio de properties (capacidad del
# archivo), distinto del gate de publicación (MIN_PHOTOS_TO_PUBLISH, en
# listings). La UI importa MAX_PHOTOS_PER_PROPERTY para el contador "máx 35";
# las views de sign/confirm lo aplican como techo — una sola fuente.
MAX_PHOTOS_PER_PROPERTY = 35
MAX_MEDIA_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB, post-resize
MEDIA_MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
ALLOWED_MEDIA_MIME_TYPES = frozenset(MEDIA_MIME_EXTENSIONS)
MEDIA_EXTENSION_MIME_TYPES = {ext: mime for mime, ext in MEDIA_MIME_EXTENSIONS.items()}


def media_mime_type_from_key(key: str) -> str | None:
    """Deriva el mime de la extensión de la key. None si la extensión no
    corresponde a un tipo permitido. La key la generó el server en sign,
    así que su extensión ya refleja el mime validado — esto la re-lee, no
    confía en un mime declarado por el cliente en confirm."""
    ext = PurePosixPath(key).suffix.lower()
    return MEDIA_EXTENSION_MIME_TYPES.get(ext)


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


def update_external_source(
    *,
    property: Property,
    agency_name: str = UNSET,
    source_url: str = UNSET,
    agreed_commission_percent: Decimal | None = UNSET,
    actor: User,
) -> ExternalPropertySource:
    """
    Corrige la fuente externa de una propiedad (§6). Contrato UNSET idéntico
    a update_property:
      - UNSET (default) → el campo no se toca.
      - "" / None → blanquear (semántica de reemplazo desde el form).
      - valor → set.
    Precondición: property.is_external. NUNCA crea la fila 1:1 por el costado
    — la invariante nace en create_property; acá se respeta por omisión y se
    rechaza si no aplica. agency_name no admite blanquear (espejo de
    create_property): "" / None se rechazan. source_url y comisión se blanquean
    libremente.
    """
    if not property.is_external:
        raise PropertyValidationError(
            "La propiedad no es externa: no tiene fuente que editar."
        )

    if agency_name is not UNSET and not agency_name:
        raise PropertyValidationError(
            "El nombre de la agencia no puede quedar vacío."
        )

    source = property.external_source

    field_values = {
        "agency_name": agency_name,
        "source_url": source_url,
        "agreed_commission_percent": agreed_commission_percent,
    }

    update_fields = ["updated_by", "updated_at"]
    for field, value in field_values.items():
        if value is not UNSET:
            setattr(source, field, value)
            update_fields.append(field)

    source.updated_by = actor
    source.save(update_fields=update_fields)

    return source


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


def reorder_property_media(
    *,
    property: Property,
    ordered_media_ids: list[UUID],
    actor: User,
) -> None:
    """
    Reemplazo total del `order` de las fotos de una propiedad.

    ordered_media_ids debe coincidir EXACTAMENTE con las fotos de la
    propiedad: mismo conjunto, sin faltantes, sin ajenas, sin repetidas.
    Cualquier desajuste rechaza sin escribir nada — un reorden es una
    permutación del set existente, nunca una alta o baja encubierta.

    Escribe solo `order`, vía bulk_update. NO toca updated_at: PropertyMedia
    se reemplaza, no se edita (mismo criterio que set_cover_media). actor
    viaja por uniformidad de la puerta de services; el modelo no tiene
    updated_by donde registrarlo.
    """
    media = list(PropertyMedia.objects.filter(property_id=property.pk))
    real_ids = {m.pk for m in media}
    requested = list(ordered_media_ids)

    if len(requested) != len(real_ids) or set(requested) != real_ids:
        raise PropertyValidationError(
            "El orden debe listar exactamente las fotos de la propiedad, "
            "sin faltantes ni repetidas."
        )

    by_id = {m.pk: m for m in media}
    for position, media_id in enumerate(requested):
        by_id[media_id].order = position

    with transaction.atomic():
        PropertyMedia.objects.bulk_update(media, ["order"])


def delete_property_media(*, media: PropertyMedia) -> None:
    """
    Hard delete del registro en DB, con promoción de portada.

    PRECONDICIÓN: el caller ya eliminó el archivo de R2 exitosamente.
    El orden de operaciones (R2 primero, DB después) es responsabilidad
    de la view — este service asume que R2 ya fue limpiado.

    Si la foto borrada era la portada y quedan otras, la primera por
    `order` (desempate por `created_at`) hereda is_cover en la misma
    transacción. Cierra la deuda de S1: se descartó el estado "con fotos
    y sin portada" — inconsistencia sin valor operativo (lista sin imagen,
    detail con fallback).
    """
    was_cover = media.is_cover
    property_id = media.property_id

    with transaction.atomic():
        media.delete()

        if was_cover:
            heir = (
                PropertyMedia.objects.filter(property_id=property_id)
                .order_by("order", "created_at")
                .first()
            )
            if heir is not None:
                heir.is_cover = True
                heir.save(update_fields=["is_cover"])