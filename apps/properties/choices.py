from django.db import models


class PropertyType(models.TextChoices):
    APARTMENT = "apartment", "Departamento"
    HOUSE = "house", "Casa"
    OFFICE = "office", "Oficina"
    COMMERCIAL = "commercial", "Local comercial"
    LAND = "land", "Terreno"
    GARAGE = "garage", "Garage"
    RURAL = "rural", "Rural"


class PropertyStatus(models.TextChoices):
    AVAILABLE   = "available"
    RENTED      = "rented"
    SOLD        = "sold"
    UNAVAILABLE = "unavailable"


class FeatureCategory(models.TextChoices):
    GENERAL         = "general", "Características generales"
    CARACTERISTICAS = "caracteristicas", "Características"
    SERVICIOS       = "servicios", "Servicios"
    AMBIENTES       = "ambientes", "Ambientes"