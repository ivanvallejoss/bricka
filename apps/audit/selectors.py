from uuid import UUID

from django.db.models import QuerySet

from .models import AuditLog


def get_entity_history(entity_type: str, entity_id: UUID) -> QuerySet:
    """
    Historial de audit log para una entidad específica.

    Punto de entrada único para consultas al audit log.
    Ninguna app importa AuditLog directamente — todas pasan por aquí.

    entity_type: usar Model.audit_entity_type() — nunca hardcodear el string.
    entity_id: UUID de la instancia.
    """
    return (
        AuditLog.objects
        .filter(entity_type=entity_type, entity_id=entity_id)
        .order_by("-created_at")
    )