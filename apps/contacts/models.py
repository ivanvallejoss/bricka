from django.conf import settings
from django.db import models

from apps.common.models import AuditableMixin
from apps.common.models import BaseModel, SoftDeleteModel, TimestampModel
from apps.listings.choices import OperationType
from .choices import ContactType, ContactRole, ContactSource, DocumentType, Currency


class Contact(SoftDeleteModel, AuditableMixin):
    """
    Persona o empresa que interactúa con la inmobiliaria.

    DECISIÓN V1: un contacto tiene un solo rol simultáneo.
    Si en el futuro un contacto puede tener múltiples roles,
    este campo requiere migración. Ver documentación de sesión.
    """
    contact_type = models.CharField(
        max_length=10,
        choices=ContactType.choices,
        default=ContactType.PERSON,
    )
    full_name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    document_type = models.CharField(
        max_length=10,
        choices=DocumentType.choices,
        blank=True,
    )
    document_number = models.CharField(max_length=20, blank=True)
    role = models.CharField(
        max_length=20,
        choices=ContactRole.choices,
        blank=True,
    )
    source = models.CharField(
        max_length=20,
        choices=ContactSource.choices,
        default=ContactSource.DIRECT,
    )
    source_detail = models.CharField(max_length=200, blank=True)
    assigned_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_contacts",
        # Semántica deliberadamente flexible: puede indicar quién originó
        # el contacto o quién lo está trabajando actualmente.
        # Editable post-creación. La inmobiliaria define su propio uso
        # con la práctica. Revisar en V2 si aparece necesidad de separar
        # ambos conceptos en campos distintos.
    )
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "contacto"
        verbose_name_plural = "contactos"


class SearchPreference(TimestampModel):
    """
    Preferencias de búsqueda de un contacto.
    Desactivación via active = False — sin soft delete.
    Un contacto puede tener múltiples preferencias activas.
    """
    contact = models.ForeignKey(
        Contact,
        on_delete=models.CASCADE,
        related_name="search_preferences",
    )
    operation_type = models.CharField(
        max_length=20,
        choices=OperationType.choices,
    )
    price_min = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    price_max = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    currency = models.CharField(
        max_length=3,
        choices=Currency.choices,
        default=Currency.ARS
    )
    area_m2_min = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
    )
    bedrooms_min = models.SmallIntegerField(null=True, blank=True)
    neighborhoods = models.JSONField(default=list, blank=True)
    property_types = models.JSONField(default=list, blank=True)
    features_required = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "preferencia de búsqueda"
        verbose_name_plural = "preferencias de búsqueda"