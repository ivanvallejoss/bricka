from django.db import models

from apps.common.models import TimestampModel
from .choices import InboundChannel, InboundEventStatus, OutboundEventStatus


class OutboundEvent(TimestampModel):
    """
    Evento saliente hacia canales externos.

    Escrito por services dentro de la misma transacción que dispara
    la acción. Procesado asincrónicamente por Celery via httpx.

    status = processing previene procesamiento doble por workers concurrentes.
    Watchdog Celery beat detecta registros en processing con updated_at
    desactualizado y los marca como failed.

    Sin AuditableMixin — Celery necesita .update() libremente sobre status,
    attempts y last_attempt_at.
    """
    event_type = models.CharField(max_length=100)
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=20,
        choices=OutboundEventStatus.choices,
        default=OutboundEventStatus.PENDING,
    )
    attempts = models.SmallIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    error_detail = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
        ]
        verbose_name = "evento saliente"
        verbose_name_plural = "eventos salientes"


class InboundEvent(TimestampModel):
    """
    Evento entrante desde canales externos.

    Flujo:
    1. Webhook receiver valida firma — si inválida: 401, sin escritura.
    2. Firma válida → escritura inmediata con status=pending. 200 OK.
    3. Celery toma el evento → status=processing, attempts += 1.
    4. Handler parsea raw_payload → contact_id se llena, status=processed.
    5. Si falla → status=failed, error_detail registrado.

    raw_payload es inmutable una vez guardado — snapshot del webhook original.
    contact_id se llena post-procesamiento, no en la escritura inicial.

    Sin AuditableMixin — mismo criterio que OutboundEvent.
    """
    channel = models.CharField(
        max_length=20,
        choices=InboundChannel.choices,
    )
    listing = models.ForeignKey(
        "listings.Listing",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="inbound_events",
    )
    contact = models.ForeignKey(
        "contacts.Contact",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="inbound_events",
    )
    raw_payload = models.JSONField()
    status = models.CharField(
        max_length=20,
        choices=InboundEventStatus.choices,
        default=InboundEventStatus.PENDING,
    )
    attempts = models.SmallIntegerField(default=0)
    processed_at = models.DateTimeField(null=True, blank=True)
    error_detail = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["channel"]),
        ]
        verbose_name = "evento entrante"
        verbose_name_plural = "eventos entrantes"