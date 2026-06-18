from django.db import models
from apps.common.choices import Currency


class ContactType(models.TextChoices):
    PERSON = "person", "Persona"
    COMPANY = "company", "Empresa"


class ContactRole(models.TextChoices):
    OWNER = "owner", "Propietario"
    TENANT = "tenant", "Inquilino"
    INTERESTED = "interested", "Interesado"


class ContactSource(models.TextChoices):
    ZONAPROP = "zonaprop", "Zonaprop"
    FACEBOOK = "facebook", "Facebook"
    INSTAGRAM = "instagram", "Instagram"
    WHATSAPP = "whatsapp", "WhatsApp"
    REFERRAL = "referral", "Referido"
    DIRECT = "direct", "Directo"
    OTHER = "other", "Otro"


class DocumentType(models.TextChoices):
    DNI = "dni", "DNI"
    CUIT = "cuit", "CUIT"
    CUIL = "cuil", "CUIL"