from django.db import models
from apps.common.choices import Currency


class OperationType(models.TextChoices):
    SALE = "sale", "Venta"
    RENT = "rent", "Alquiler"
    TEMPORARY_RENT = "temporary_rent", "Alquiler temporario"


class ListingStatus(models.TextChoices):
    DRAFT = "draft", "Borrador"
    PENDING_APPROVAL = "pending_approval", "Pendiente de aprobación"
    PUBLISHED = "published", "Publicado"
    PAUSED = "paused", "Pausado"
    CLOSED = "closed", "Cerrado"


class PricePeriod(models.TextChoices):
    TOTAL = "total", "Total"
    MONTHLY = "monthly", "Mensual"
    DAILY = "daily", "Diario"


class PublicationChannel(models.TextChoices):
    OWN_WEBSITE = "own_website", "Sitio propio"
    ZONAPROP = "zonaprop", "Zonaprop"
    FACEBOOK = "facebook", "Facebook"
    INSTAGRAM = "instagram", "Instagram"
    MERCADOLIBRE = "mercadolibre", "MercadoLibre"


class PublicationStatus(models.TextChoices):
    PENDING = "pending", "Pendiente"
    PUBLISHED = "published", "Publicado"
    FAILED = "failed", "Fallido"
    UNPUBLISHED = "unpublished", "Despublicado"