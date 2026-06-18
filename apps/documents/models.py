from django.conf import settings
from django.db import models

from apps.common.models import AuditableMixin, SoftDeleteModel


class Document(SoftDeleteModel, AuditableMixin):
    """
    Documento legal asociado a una o más entidades del sistema.

    INVARIANTE: al menos una FK padre debe estar presente.
    Este contrato lo garantiza documents.services — no hay constraint en DB.

    Borrado: soft delete por defecto. Hard delete disponible desde
    vista de papelera — siempre R2 primero, DB después.
    Las instancias soft-deleted no se exponen en ningún selector
    estándar — solo en get_deleted_documents() para la papelera.
    """

    contact = models.ForeignKey(
        "contacts.Contact",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    property = models.ForeignKey(
        "properties.Property",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    deal = models.ForeignKey(
        "deals.Deal",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    contract = models.ForeignKey(
        "contracts.RentalContract",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    original_filename = models.CharField(max_length=255)
    r2_key = models.CharField(max_length=500, unique=True)
    content_type = models.CharField(max_length=100)
    file_size = models.PositiveIntegerField()
    description = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = "documento"
        verbose_name_plural = "documentos"