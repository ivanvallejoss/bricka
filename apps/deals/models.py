from django.conf import settings
from django.db import models

from apps.common.models import BaseModel, SoftDeleteModel, TimestampModel, AuditableMixin
from .choices import DealType, DealOutcome, PipelineType


class PipelineStage(TimestampModel):
    """
    Etapas del pipeline de ventas y alquileres.

    V1: una etapa default por tipo, cargada via data migration.
    stage_id en Deal es nullable — ningún flujo de V1 requiere
    interacción con esta tabla.
    Activación del pipeline visual diferida a V2.
    """
    pipeline_type = models.CharField(
        max_length=10,
        choices=PipelineType.choices,
    )
    name = models.CharField(max_length=100)
    order = models.SmallIntegerField(default=0)
    is_terminal_won = models.BooleanField(default=False)
    is_terminal_lost = models.BooleanField(default=False)

    class Meta:
        ordering = ["pipeline_type", "order"]
        verbose_name = "etapa de pipeline"
        verbose_name_plural = "etapas de pipeline"


class Deal(SoftDeleteModel, AuditableMixin):
    """
    Negociación sobre una propiedad — venta o alquiler.

    listing_id es nullable para cubrir deals sobre propiedades ajenas
    donde los socios no quieren registrar el listing completo.
    INVARIANTE: listing_id o external_property_notes debe estar presente.
    El check constraint lo garantiza a nivel DB.

    stage_id es nullable en V1 — pipeline visual diferido a V2.

    Operaciones atómicas: cambios de etapa deben escribir
    simultáneamente en esta tabla y en DealStageHistory.
    """
    deal_type = models.CharField(
        max_length=10,
        choices=DealType.choices,
    )
    listing = models.ForeignKey(
        "listings.Listing",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="deals",
    )
    external_property_notes = models.TextField(blank=True)
    client_contact = models.ForeignKey(
        "contacts.Contact",
        on_delete=models.PROTECT,
        related_name="deals",
    )
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_deals",
    )
    stage = models.ForeignKey(
        PipelineStage,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="deals",
    )
    outcome = models.CharField(
        max_length=20,
        choices=DealOutcome.choices,
        blank=True,
    )
    expected_close_date = models.DateField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "negociación"
        verbose_name_plural = "negociaciones"
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(listing__isnull=False) |
                    models.Q(external_property_notes__gt="")
                ),
                name="deal_requires_listing_or_notes",
            )
        ]


class DealStageHistory(TimestampModel):
    """
    Historial inmutable de cambios de etapa en un deal.

    Tabla append-only — sin updated_at semántico.
    created_by registra quién ejecutó el cambio de etapa.
    Siempre se escribe en la misma transacción que Deal.stage.
    Sin uso activo en V1 — estructura lista para V2.
    """
    deal = models.ForeignKey(
        Deal,
        on_delete=models.PROTECT,
        related_name="stage_history",
    )
    stage = models.ForeignKey(
        PipelineStage,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "historial de etapa"
        verbose_name_plural = "historial de etapas"