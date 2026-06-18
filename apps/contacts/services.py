from django.contrib.auth import get_user_model

from .choices import ContactSource, ContactType
from .exceptions import ContactHasOpenDeals
from .models import Contact
from apps.deals.selectors import get_open_deals_for_contact

User = get_user_model()


def create_contact(
    *,
    full_name: str,
    contact_type: str = ContactType.PERSON,
    email: str = "",
    phone: str = "",
    document_type: str = "",
    document_number: str = "",
    role: str = "",
    source: str = ContactSource.DIRECT,
    source_detail: str = "",
    assigned_agent: User | None = None,
    notes: str = "",
    actor: User,
) -> Contact:
    contact = Contact(
        full_name=full_name,
        contact_type=contact_type,
        email=email,
        phone=phone,
        document_type=document_type,
        document_number=document_number,
        role=role,
        source=source,
        source_detail=source_detail,
        assigned_agent=assigned_agent,
        notes=notes,
        created_by=actor,
        updated_by=actor,
    )
    contact.save()
    return contact


def update_contact(
    contact: Contact,
    *,
    full_name: str,
    contact_type: str,
    email: str,
    phone: str,
    document_type: str,
    document_number: str,
    role: str,
    source: str,
    source_detail: str,
    assigned_agent: User | None,
    notes: str,
    actor: User,
) -> Contact:
    contact.full_name = full_name
    contact.contact_type = contact_type
    contact.email = email
    contact.phone = phone
    contact.document_type = document_type
    contact.document_number = document_number
    contact.role = role
    contact.source = source
    contact.source_detail = source_detail
    contact.assigned_agent = assigned_agent
    contact.notes = notes
    contact.updated_by = actor
    contact.save(update_fields=[
        "full_name", "contact_type", "email", "phone",
        "document_type", "document_number", "role",
        "source", "source_detail", "assigned_agent",
        "notes", "updated_by", "updated_at",
    ])
    return contact


def archive_contact(contact: Contact, actor: User) -> Contact:
    """
    Archiva un contacto.
    Raises ContactHasOpenDeals si existen negociaciones activas.

    ⚠️ DEUDA: cuando se implemente documents/, agregar archivado
    de documentos asociados aquí dentro de transaction.atomic().
    """
    if get_open_deals_for_contact(contact.pk).exists():
        raise ContactHasOpenDeals()
    contact.soft_delete(actor=actor)
    return contact


def restore_contact(contact: Contact, actor: User) -> Contact:
    contact.restore(actor=actor)
    return contact