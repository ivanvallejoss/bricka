from django.db import models
from .querysets import AuditedQuerySet, AuditedSoftDeleteQuerySet


class AuditedSoftDeleteManager(models.Manager):
    """
    Manager default de SoftDeleteModel.
    Filtra registros borrados y protege operaciones bulk
    """
    def get_queryset(self):
        return AuditedSoftDeleteQuerySet(
            self.model, using=self._db
        ).filter(deleted_at__isnull=True)


class AllObjectsManager(models.Manager):
    """
    Manager sin filtro de soft delete.
    Uso explícito y FK traversal (base_manager_name).
    """
    def get_queryset(self):
        return AuditedSoftDeleteQuerySet(self.model, using=self._db)


class AuditedManager(models.Manager):
    """
    Manager para modelos auditables sin soft delete (ej: BillingDocument).
    """
    def get_queryset(self):
        return AuditedQuerySet(self.model, using=self._db)