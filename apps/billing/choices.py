from django.db import models


class DocumentType(models.TextChoices):
    RENT_RECEIPT = "rent_receipt", "Recibo de alquiler"
    COMMISSION_RECEIPT = "commission_receipt", "Recibo de comisión"
    EXPENSE_RECEIPT = "expense_receipt", "Recibo de gasto"
    OWNER_STATEMENT = "owner_statement", "Rendición de cuentas"


class DocumentStatus(models.TextChoices):
    ISSUED = "issued", "Emitido"
    CANCELLED = "cancelled", "Cancelado"


class PaymentStatus(models.TextChoices):
    PAID = "paid", "Pago"
    PENDING = "pending", "Pendiente de pago"
    OVERDUE = "overdue", "En mora"
    NOT_APPLICABLE = "not_applicable", "No aplica"


class ConceptLineType(models.TextChoices):
    RENT = "rent", "Alquiler"
    COMMISSION = "commission", "Comisión"
    MORA = "mora", "Mora"
    ADJUSTMENT = "adjustment", "Ajuste"
    EXPENSE = "expense", "Expensas"
    OTHER_CHARGE = "other_charge", "Otro (cargo)"     
    OTHER_CREDIT = "other_credit", "Otro (haber)"     