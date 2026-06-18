from dataclasses import dataclass, field
from uuid import UUID

from django.db import transaction

from apps.users.models import User
from apps.documents.exceptions import DocumentValidationError
from apps.documents.models import Document


@dataclass
class DocumentUploadItem:
    r2_key: str
    original_filename: str
    content_type: str
    file_size: int
    description: str = ""


def upload_documents(
    *,
    items: list[DocumentUploadItem],
    contact_id: UUID | None = None,
    property_id: UUID | None = None,
    deal_id: UUID | None = None,
    contract_id: UUID | None = None,
    actor: User,
) -> list[Document]:
    if not any([contact_id, property_id, deal_id, contract_id]):
        raise DocumentValidationError(
            "Un documento debe tener al menos una entidad asociada."
        )

    if not items:
        raise DocumentValidationError(
            "Se requiere al menos un archivo para subir."
        )

    with transaction.atomic():
        documents = []
        for item in items:
            doc = Document(
                contact_id=contact_id,
                property_id=property_id,
                deal_id=deal_id,
                contract_id=contract_id,
                r2_key=item.r2_key,
                original_filename=item.original_filename,
                content_type=item.content_type,
                file_size=item.file_size,
                description=item.description,
                created_by=actor,
                updated_by=actor,
            )
            doc.save()
            documents.append(doc)

    return documents


def soft_delete_document(*, document: Document, actor: User) -> Document:
    document.soft_delete(actor=actor)
    return document


def hard_delete_document(*, document: Document) -> None:
    """
    Eliminación física permanente del registro en DB.

    PRECONDICIONES:
    - El caller ya eliminó el archivo de R2 exitosamente (R2 primero, DB después).
    - El documento ya está soft-deleted — solo se llama desde la vista de papelera.

    Usa _raw_delete para bypasear AuditViolationError intencionalmente.
    Excepción documentada — el único camino válido para hard delete
    en un modelo auditado sin _default_manager en service.

    ⚠️ El hard delete bypasea el audit log — los documentos eliminados
    físicamente no dejan registro de auditoría. Trade-off aceptado.
    """
    Document.all_objects.filter(pk=document.pk)._raw_delete(using="default")