from django.db import models


class DealType(models.TextChoices):
    SALE = "sale", "Venta"
    RENT = "rent", "Alquiler"


class DealOutcome(models.TextChoices):
    WON = "won", "Ganado"
    LOST = "lost", "Perdido"
    CANCELLED = "cancelled", "Cancelado"


class PipelineType(models.TextChoices):
    SALE = "sale", "Venta"
    RENT = "rent", "Alquiler"