from django.conf import settings
from django.db import models

from apps.common.choices import Currency
from apps.common.models import BaseModel, SoftDeleteModel, TimestampModel
from apps.common.models import AuditableMixin
from .choices import AdjustmentIndex, GuaranteeType, ContractStatus


class RentalContract(SoftDeleteModel, AuditableMixin):
    """
    Contrato de alquiler entre propietario e inquilino.

    Campos de mora:
    - payment_due_day: día del mes en que vence el pago (ej: 10)
    - late_fee_percent_daily: porcentaje diario acumulable por mora (default 2%)

    Celery evalúa mora una vez por día comparando la fecha actual
    contra payment_due_day. El cálculo es un selector puro —
    no se persiste estado de mora en la DB.
    La mora se materializa únicamente en billing_documents.concept
    cuando el socio emite el recibo.

    Operaciones atómicas: aprobación de ajuste debe escribir
    simultáneamente current_price + next_adjustment_date en esta
    tabla y una nueva fila en RentAdjustment.
    """
    deal = models.ForeignKey(
        "deals.Deal",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contracts",
    )
    property = models.ForeignKey(
        "properties.Property",
        on_delete=models.PROTECT,
        related_name="rental_contracts",
    )
    tenant_contact = models.ForeignKey(
        "contacts.Contact",
        on_delete=models.PROTECT,
        related_name="tenant_contracts",
    )
    owner_contact = models.ForeignKey(
        "contacts.Contact",
        on_delete=models.PROTECT,
        related_name="owner_contracts",
    )
    start_date = models.DateField()
    end_date = models.DateField()
    initial_price = models.DecimalField(max_digits=14, decimal_places=2)
    current_price = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(
        max_length=3,
        choices=Currency.choices,
        default=Currency.ARS,
    )
    payment_due_day = models.SmallIntegerField()
    late_fee_percent_daily = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=2,
    )
    adjustment_index = models.CharField(
        max_length=20,
        choices=AdjustmentIndex.choices,
    )
    adjustment_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    adjustment_frequency_months = models.SmallIntegerField()
    next_adjustment_date = models.DateField()
    deposit_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    guarantee_type = models.CharField(
        max_length=30,
        choices=GuaranteeType.choices,
    )
    guarantee_detail = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=ContractStatus.choices,
        default=ContractStatus.ACTIVE,
    )

    class Meta:
        verbose_name = "contrato de alquiler"
        verbose_name_plural = "contratos de alquiler"
        constraints = [
            models.CheckConstraint(
                check=models.Q(
                    adjustment_index="fixed_percent",
                    adjustment_percent__isnull=False,
                ) | ~models.Q(adjustment_index="fixed_percent"),
                name="fixed_percent_requires_adjustment_percent",
            ),
            models.CheckConstraint(
                check=models.Q(payment_due_day__gte=1) &
                      models.Q(payment_due_day__lte=28),
                name="payment_due_day_valid_range",
            ),
        ]


class RentAdjustment(TimestampModel):
    """
    Registro inmutable de un ajuste de precio aprobado.

    applied_by es no nullable + PROTECT — excepción explícita
    a la convención general SET_NULL.
    Este registro certifica quién aprobó el ajuste.
    Sin ese dato el registro pierde su valor auditivo completo.

    Flujo:
    1. Celery calcula valor propuesto y lo presenta al socio.
    2. Socio aprueba desde el backoffice.
    3. Transacción atómica:
       - RentalContract.current_price = new_price
       - RentalContract.next_adjustment_date recalculada
       - Nueva fila en RentAdjustment
    """
    contract = models.ForeignKey(
        RentalContract,
        on_delete=models.PROTECT,
        related_name="adjustments",
    )
    adjustment_date = models.DateField()
    previous_price = models.DecimalField(max_digits=14, decimal_places=2)
    new_price = models.DecimalField(max_digits=14, decimal_places=2)
    index_used = models.CharField(
        max_length=20,
        choices=AdjustmentIndex.choices,
    )
    index_value_at_date = models.DecimalField(
        max_digits=10,
        decimal_places=4,
    )
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        ordering = ["-adjustment_date"]
        verbose_name = "ajuste de alquiler"
        verbose_name_plural = "ajustes de alquiler"