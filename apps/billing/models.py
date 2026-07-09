from django.db import models

from apps.common.choices import Currency
from apps.common.models import BaseModel, AuditableMixin
from .choices import DocumentType, DocumentStatus


class BillingDocument(BaseModel, AuditableMixin):
    """
    Comprobante de cobro interno — alquiler, comisión, gasto o rendición.

    INMUTABILIDAD: una vez emitido, este registro nunca se modifica.
    El único cambio de estado permitido es issued → cancelled, vía el
    campo status, no como modificación del comprobante original.
    El service es el único punto válido de creación — nunca .save()
    sobre una instancia existente para alterar su contenido.

    NUMERACIÓN: number se asigna via PostgreSQL sequence por document_type
    en billing/services.py. Trade-off aceptado: gaps posibles si una
    transacción hace rollback tras consumir nextval(). Incompatible con
    AFIP — reemplazar cuando se active integración fiscal.

    TOTAL AUTORITATIVO: total_amount es la cifra legalmente significativa.
    concept es el desglose (lista de renglones). El service garantiza el
    invariante total_amount == suma de los amounts de concept al emitir.
    No se deriva en read-time — se congela al emitir.

    PRESENCIA DE FK POR TIPO (validada en el service, no en DB — ver
    opción B en docs/decisions/design.md):
      - RENT_RECEIPT     → contract obligatorio, period obligatorio
      - EXPENSE_RECEIPT  → contract obligatorio
      - COMMISSION_RECEIPT → deal obligatorio
      - OWNER_STATEMENT  → contract y deal null; period obligatorio;
                           contratos liquidados referenciados en concept

    recipient_contact: a quién va dirigido el comprobante. Para
    RENT/EXPENSE/COMMISSION es quien paga; para OWNER_STATEMENT es el
    propietario que cobra el neto. Nombre neutral a la dirección del dinero.

    period: mes facturado, persistido como primer día del mes. Distinto de
    date (fecha de emisión). Un recibo de marzo emitido en mayo tiene
    date=mayo, period=2026-03-01. El badge de estado de pago consulta period.

    BaseModel genera `created_by` y `updated_by`
    """
    deal = models.ForeignKey(
        "deals.Deal",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="billing_documents",
    )
    contract = models.ForeignKey(
        "contracts.RentalContract",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="billing_documents",
    )
    document_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices,
    )
    number = models.PositiveIntegerField()
    date = models.DateField()
    period = models.DateField(null=True, blank=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(
        max_length=3,
        choices=Currency.choices,
        default=Currency.ARS,
    )
    concept = models.JSONField(default=list)
    recipient_contact = models.ForeignKey(
        "contacts.Contact",
        on_delete=models.PROTECT,
        related_name="billing_documents",
    )
    status = models.CharField(
        max_length=20,
        choices=DocumentStatus.choices,
        default=DocumentStatus.ISSUED,
    )
    recipient_name = models.CharField(max_length=255, default="")
    recipient_document_type = models.CharField(max_length=20, default="", blank=True)
    recipient_document_number = models.CharField(max_length=50, default="", blank=True)

    class Meta:
        verbose_name = "comprobante"
        verbose_name_plural = "comprobantes"
        constraints = [
            models.UniqueConstraint(
                fields=["document_type", "number"],
                name="unique_number_per_document_type",
            ),
            models.UniqueConstraint(
                fields=["contract", "period"],
                condition=models.Q(document_type="rent_receipt", status="issued"),
                name="unique_issued_rent_receipt_per_period",
            ),
            models.UniqueConstraint(
                fields=["contract", "period"],
                condition=models.Q(document_type="expense_receipt", status="issued"),
                name="unique_issued_expense_receipt_per_period",
            ),
        ]
        indexes = [
            models.Index(
                fields=["contract", "document_type", "period"],
                name="billing_badge_lookup_idx",
            ),
        ]