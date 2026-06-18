from dataclasses import dataclass
from uuid import UUID

from django.db.models import QuerySet

from apps.documents.models import Document


@dataclass
class DocumentFilters:
    contact_id: UUID | None = None
    property_id: UUID | None = None
    deal_id: UUID | None = None
    contract_id: UUID | None = None


def _apply_filters(qs: QuerySet, filters: DocumentFilters) -> QuerySet:
    if filters.contact_id is not None:
        qs = qs.filter(contact_id=filters.contact_id)
    if filters.property_id is not None:
        qs = qs.filter(property_id=filters.property_id)
    if filters.deal_id is not None:
        qs = qs.filter(deal_id=filters.deal_id)
    if filters.contract_id is not None:
        qs = qs.filter(contract_id=filters.contract_id)
    return qs


def get_document_list(
    filters: DocumentFilters | None = None,
) -> QuerySet[Document]:
    qs = Document.objects.select_related(
        "contact",
        "property",
        "deal",
        "contract",
        "created_by",
    )
    if filters is None:
        return qs
    return _apply_filters(qs, filters)


def get_document_detail(document_id: UUID) -> Document:
    try:
        return Document.objects.select_related(
            "contact",
            "property",
            "deal",
            "contract",
            "created_by",
        ).get(pk=document_id)
    except Document.DoesNotExist:
        raise


def get_deleted_documents(
    filters: DocumentFilters | None = None,
) -> QuerySet[Document]:
    """
    Selector exclusivo para la vista de papelera.
    Solo devuelve documentos soft-deleted.
    """
    qs = Document.all_objects.filter(
        deleted_at__isnull=False,
    ).select_related(
        "contact",
        "property",
        "deal",
        "contract",
        "created_by",
    )
    if filters is None:
        return qs
    return _apply_filters(qs, filters)