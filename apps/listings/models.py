from django.conf import settings
from django.db import models

from apps.common.models import AuditableMixin
from apps.common.models import BaseModel, SoftDeleteModel, TimestampModel
from .choices import (
    OperationType,
    ListingStatus,
    PricePeriod,
    Currency,
    PublicationChannel,
    PublicationStatus,
)


class Listing(SoftDeleteModel, AuditableMixin):
    """
    Publicación de una propiedad para venta o alquiler.

    CAMPO SENSIBLE: price_min_acceptable nunca se expone
    en ninguna vista pública ni selector del portal.
    Acceso restringido al backoffice.

    Operaciones atómicas: cambios de precio deben escribir
    simultáneamente en esta tabla y en ListingPriceHistory.
    El service es el único punto válido para modificar price.
    """
    property = models.ForeignKey(
        "properties.Property",
        on_delete=models.PROTECT,
        related_name="listings",
    )
    operation_type = models.CharField(
        max_length=20,
        choices=OperationType.choices,
    )
    price = models.DecimalField(max_digits=14, decimal_places=2)
    price_min_acceptable = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    currency = models.CharField(
        max_length=3,
        choices=Currency.choices,
        default=Currency.ARS,
    )
    period = models.CharField(
        max_length=20,
        choices=PricePeriod.choices,
        default=PricePeriod.TOTAL,
    )
    status = models.CharField(
        max_length=20,
        choices=ListingStatus.choices,
        default=ListingStatus.DRAFT,
    )
    available_from = models.DateField(null=True, blank=True)
    available_until = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "publicación"
        verbose_name_plural = "publicaciones"
        constraints = [
            models.UniqueConstraint(
                fields=["property", "operation_type"],
                condition=models.Q(
                    status__in=["published", "paused"],
                    deleted_at__isnull=True,
                ),
                name="unique_active_listing_per_operation",
            )
        ]


class ListingPriceHistory(TimestampModel):
    """
    Historial inmutable de cambios de precio en un listing.

    Tabla append-only — sin updated_at semántico.
    created_by registra quién autorizó el cambio de precio.
    Siempre se escribe en la misma transacción que Listing.price.
    """
    listing = models.ForeignKey(
        Listing,
        on_delete=models.PROTECT,
        related_name="price_history",
    )
    price = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, choices=Currency.choices)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "historial de precio"
        verbose_name_plural = "historial de precios"


class ListingPublication(BaseModel):
    """
    Estado de publicación de un listing en un canal externo.

    Sin soft delete — el historial de publicaciones tiene valor auditivo.
    created_by: quién autorizó la publicación (humano).
    updated_by: null en actualizaciones de estado por Celery — convención del sistema.

    metadata almacena payload específico por canal (IDs externos,
    respuestas de API, datos de sincronización).
    """
    listing = models.ForeignKey(
        Listing,
        on_delete=models.PROTECT,
        related_name="publications",
    )
    channel = models.CharField(
        max_length=20,
        choices=PublicationChannel.choices,
    )
    external_id = models.CharField(max_length=200, blank=True)
    status = models.CharField(
        max_length=20,
        choices=PublicationStatus.choices,
        default=PublicationStatus.PENDING,
    )
    published_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "publicación en canal"
        verbose_name_plural = "publicaciones en canales"
        constraints = [
            models.UniqueConstraint(
                fields=["listing", "channel"],
                name="unique_listing_channel",
            )
        ]