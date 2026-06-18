from django.db import models


class Currency(models.TextChoices):
    ARS = "ARS", "Pesos"
    USD = "USD", "Dólares"