from django.contrib.gis.db.models import PointField
from django.conf import settings
from django.db import models

from apps.common.models import BaseModel, SoftDeleteModel, TimestampModel
from apps.common.models import AuditableMixin
from .choices import PropertyType, PropertyStatus


class Property(SoftDeleteModel, AuditableMixin):
    """
    Unidad inmobiliaria — propia o de otra inmobiliaria (is_external).

    INVARIANTE: si is_external = True, debe existir exactamente una fila
    en ExternalPropertySource con property = self.id.
    Este contrato lo mantiene properties.services — no hay constraint en DB.

    NOTA DE PRESENTACIÓN PENDIENTE: propiedades externas requieren
    tratamiento visual diferenciado en templates y selectors del backoffice.
    Ver documentación de sesión — pendiente antes de implementar vistas.
    """
    title = models.CharField(max_length=150, blank=True)
    description = models.TextField()
    property_type = models.CharField(
        max_length=20,
        choices=PropertyType.choices,
    )
    address_line = models.TextField()
    city = models.CharField(max_length=100)
    neighborhood = models.CharField(max_length=100, blank=True)
    province = models.CharField(max_length=100)
    location = PointField(null=True, blank=True)
    area_m2 = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    bedrooms = models.SmallIntegerField(null=True, blank=True)
    bathrooms = models.SmallIntegerField(null=True, blank=True)
    year_built = models.SmallIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=PropertyStatus.choices,
        default=PropertyStatus.AVAILABLE,
    )
    owner_contact = models.ForeignKey(
        "contacts.Contact",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_properties",
    )
    is_external = models.BooleanField(default=False)
    features = models.JSONField(default=dict, blank=True)
    youtube_video_url = models.URLField(blank=True)

    class Meta:
        verbose_name = "propiedad"
        verbose_name_plural = "propiedades"


class ExternalPropertySource(BaseModel):
    """
    Detalle de origen para propiedades de otras inmobiliarias.
    Existe únicamente cuando Property.is_external = True.
    Relación 1:1 con Property.

    No hereda SoftDeleteModel — el ciclo de vida lo controla Property.
    Si la propiedad se soft-deletes, esta fila queda huérfana intencionalmente
    como registro histórico.
    """
    property = models.OneToOneField(
        Property,
        on_delete=models.CASCADE,
        related_name="external_source",
    )
    agency_name = models.CharField(max_length=200)
    source_url = models.URLField(blank=True)
    agreed_commission_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "fuente externa"
        verbose_name_plural = "fuentes externas"


class PropertyMedia(TimestampModel):
    """
    Archivos multimedia de una propiedad.

    Hereda TimestampModel — las fotos se reemplazan, no se editan.
    updated_by no tiene semántica real en este contexto.
    created_by se declara manualmente para saber quién subió el archivo.

    Borrado: hard delete coordinado con R2.
    Sin soft delete — una foto borrada no tiene valor histórico.
    """
    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="media",
    )
    r2_key = models.CharField(max_length=500, unique=True)
    mime_type = models.CharField(max_length=100)
    order = models.SmallIntegerField(default=0)
    is_cover = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["order"]
        verbose_name = "archivo multimedia"
        verbose_name_plural = "archivos multimedia"