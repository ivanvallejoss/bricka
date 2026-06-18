from django.db import models


class AdjustmentIndex(models.TextChoices):
    ICL = "ICL", "ICL (BCRA)"
    IPC = "IPC", "IPC (INDEC)"
    CVS = "CVS", "CVS (INDEC)"
    FIXED_PERCENT = "fixed_percent", "Porcentaje fijo"


class GuaranteeType(models.TextChoices):
    PROPERTY_GUARANTEE = "property_guarantee", "Garantía propietaria"
    INSURANCE = "insurance", "Seguro de caución"
    BANK_GUARANTEE = "bank_guarantee", "Aval bancario"
    DIRECT_DEBIT = "direct_debit", "Débito directo"
    OTHER = "other", "Otro"


class ContractStatus(models.TextChoices):
    ACTIVE = "active", "Activo"
    SCHEDULED = "scheduled", "Programado"
    EXPIRED = "expired", "Vencido"
    TERMINATED = "terminated", "Rescindido"