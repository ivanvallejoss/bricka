from django.db import models
from .exceptions import AuditViolationError

class SoftDeleteQuerySet(models.QuerySet):
    """QuerySet base para modelos con soft delete. Sin ogica propia"""
    pass

class AuditedQuerySet(models.QuerySet):
    """
    Refuerzo de integridad del audit log
    Impide operaciones bulk que salteen signals
    """
    def update(self, **kwargs):
        raise AuditViolationError(
            f"El metodo .update() no esta permitido en {self.model.__name__}. "
            f"Utiliza el metodo del servicio apropiado para mantener la integridad del audit log."
        )

    def delete(self):
        raise AuditViolationError(
            f"El metodo .delete() no esta permitido {self.model.__name__}. "
            f"utilizar el metodo .soft_delete() o el metodo de servicio correspondiente."
        )


class AuditedSoftDeleteQuerySet(AuditedQuerySet, SoftDeleteQuerySet):
    """
    Capa de integración — sin lógica propia
    Hereda enforcement de audit y base de soft delete
    """
    pass