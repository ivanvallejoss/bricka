import uuid
from django.db import models


class AuditAction(models.TextChoices):
    CREATE = "create", "Creación"
    UPDATE = "update", "Actualización"
    DELETE = "delete", "Borrado"
    RESTORE = "restore", "Restauración"


class AuditLog(models.Model):
    """
    Registro histórico inmutable de cambios en entidades auditadas.

    No hereda de ningún modelo base — único en su naturaleza.
    Sin updated_at, sin deleted_at, sin soft delete.

    actor_id es UUIDField sin FK — snapshot histórico, no referencia viva.
    Razón: FK + SET_NULL perdería la identidad del actor ante borrado físico.
    FK + PROTECT impediría borrar usuarios con historial.
    UUID preserva la identidad permanentemente sin restricciones.

    ip_address: null en acciones de Celery y en V1 — requiere middleware
    para capturarse desde el contexto de request. Diferido a cuando
    exista un caso de uso que lo justifique.

    before/after: estado completo serializado del objeto.
    Capturados via pre_save + post_save en audit/signals.py.
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    actor_id = models.UUIDField(null=True, blank=True)
    action = models.CharField(
        max_length=10,
        choices=AuditAction.choices,
    )
    entity_type = models.CharField(max_length=100)
    entity_id = models.UUIDField()
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["actor_id"]),
            models.Index(fields=["created_at"]),
        ]
        verbose_name = "registro de auditoría"
        verbose_name_plural = "registros de auditoría"