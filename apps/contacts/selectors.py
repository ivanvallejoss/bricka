from dataclasses import dataclass
from uuid import UUID

from django.db.models import QuerySet, Q

from apps.audit.selectors import get_entity_history
from .models import Contact, SearchPreference


@dataclass
class ContactFilters:
    role: str | None = None
    source: str | None = None
    assigned_agent_id: UUID | None = None
    search: str | None = None


def get_contact_list(filters: ContactFilters | None = None) -> QuerySet:
    """
    Lista de contactos activos con assigned_agent prefetcheado.
    El manager default ya excluye soft-deleted.
    """
    qs = Contact.objects.select_related("assigned_agent")

    if filters is None:
        return qs

    if filters.role is not None:
        qs = qs.filter(role=filters.role)
    if filters.source is not None:
        qs = qs.filter(source=filters.source)
    if filters.assigned_agent_id is not None:
        qs = qs.filter(assigned_agent_id=filters.assigned_agent_id)
    if filters.search:
        qs = qs.filter(
            Q(full_name__icontains=filters.search) |
            Q(phone__icontains=filters.search)
        )

    return qs


def get_contact_detail(contact_id: UUID) -> Contact:
    """
    Detalle de un contacto activo.
    Raises Contact.DoesNotExist si no existe o está soft-deleted.
    El manager default excluye soft-deleted — ambos casos devuelven
    la misma excepción intencionalmente.
    El caller decide cómo manejarla (404 en views, re-raise en services).
    """
    return (
        Contact.objects
        .select_related("assigned_agent")
        .get(pk=contact_id)
    )


def get_contact_history(contact_id: UUID) -> QuerySet:
    """
    Historial de audit log para un contacto.
    Delega a audit/selectors — contacts no importa AuditLog directamente.
    """
    return get_entity_history(Contact.audit_entity_type(), contact_id)


def get_search_preferences_for_contact(contact_id: UUID) -> QuerySet:
    """
    Devuelve las preferencias del contacto.
    Utilizado en el template `contact_detail`
    """
    return SearchPreference.objects.filter(contact_id=contact_id, active=True)