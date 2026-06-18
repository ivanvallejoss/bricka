import uuid
from django.db import models
from django.utils import timezone
from django.conf import settings
from .managers import AuditedSoftDeleteManager, AllObjectsManager, AuditedManager


class BaseModel(models.Model):
    """
    Clase base para todos los modelos del sistema.

    Todos los modelos heredan de aquí directamente o via SoftDeleteModel.
    - created_by / updated_by: null = acción ejecutada por el sistema (Celery).
    - No aplicar a tablas de infraestructura que necesiten bulk ops
    (InboundEvent, OutboundEvent, AuditLog).
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        abstract = True


class SoftDeleteModel(BaseModel):
    """
    Extiende BaseModel con soft delete y enforcement de audit.

    - objects: manager filtrado (deleted_at IS NULL). Uso default.
    - all_objects: manager sin filtro. Uso explícito cuando se necesita
      acceder a registros archivados.
    - base_manager_name = "all_objects": FK traversal nunca explota
      aunque el registro relacionado esté soft-deleted.
    - .update() y .delete() en queryset levantan AuditViolationError.
      Usar instance.soft_delete() o el service correspondiente.
    """
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = AuditedSoftDeleteManager()
    all_objects = AllObjectsManager()

    def soft_delete(self, actor=None):
        """
        Único punto de borrado en modelos auditados.
        Dispara post_save signal → audit_log.
        actor es opcional — None indica acción del sistema.

        ⚠️  DEUDA CONOCIDA: cuando actor=None, updated_by no se limpia.
        Si el modelo tenía updated_by=user_X de la última edición,
        el audit log registra ese soft_delete con actor=user_X.
        Atribución incorrecta para acciones ejecutadas por Celery.

        No se activa en Contact (archive siempre es acción humana).
        Se activa en Listing y RentalContract cuando Celery dispara
        archivos automáticos. Corregir antes de implementar esos flujos.
        Fix: self.updated_by = actor (incondicional).
        """
        self.deleted_at = timezone.now()
        self.updated_by = actor
        self.save(update_fields=["deleted_at", "updated_by", "updated_at"])

    def restore(self, actor=None):
        """
        Restaura un registro soft-deleted.
        Dispara post_save signal → audit_log.

        ⚠️  DEUDA CONOCIDA: cuando actor=None, updated_by no se limpia.
        Si el modelo tenía updated_by=user_X de la última edición,
        el audit log registra ese soft_delete con actor=user_X.
        Atribución incorrecta para acciones ejecutadas por Celery.

        No se activa en Contact (archive siempre es acción humana).
        Se activa en Listing y RentalContract cuando Celery dispara
        archivos automáticos. Corregir antes de implementar esos flujos.
        Fix: self.updated_by = actor (incondicional).
        """
        self.deleted_at = None
        self.updated_by = actor
        self.save(update_fields=["deleted_at", "updated_by", "updated_at"])

    class Meta:
        abstract = True
        base_manager_name = "all_objects"


class AuditableMixin(models.Model):
    """
    Enforcement de audit para modelos sin soft delete (ej: BillingDocument).

    Aplica solo cuando el modelo NO hereda SoftDeleteModel.
    Si hereda SoftDeleteModel, el enforcement ya está incluido.
    """
    objects = AuditedManager()

    @classmethod
    def audit_entity_type(cls) -> str:
        """
        Identificador canonico del modelo para el audit log.
        Usado al escribir (signals) y al leer (selectors).
        Nunca hardcodear el string - siempre llamar este metodo.
        """
        return cls.__name__

    class Meta:
        abstract = True


class TimestampModel(models.Model):
    """
    Base para tablas auxiliares que no necesitan trazabilidad de usuario.
    Solo UUID PK y timestamps.

    Usar cuando:
    - La tabla es append-only o sus filas se reemplazan, no se editan.
    - updated_by no tiene semántica real (siempre sería null).

    Ejemplos: PropertyMedia, ListingPriceHistory, DealStageHistory, RentAdjustment.
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True