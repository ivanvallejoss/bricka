import uuid

import pytest

from apps.contacts.tests.factories import ContactFactory
from apps.documents.models import Document
from apps.documents.selectors import (
    DocumentFilters,
    get_deleted_documents,
    get_document_detail,
    get_document_list,
)
from apps.documents.services import soft_delete_document
from apps.documents.tests.factories import DocumentFactory
from apps.properties.tests.factories import PropertyFactory


class TestGetDocumentList:
    def test_returns_active_documents(self, db):
        DocumentFactory.create_batch(2)
        assert get_document_list().count() == 2

    def test_excludes_soft_deleted(self, db, actor):
        active = DocumentFactory(r2_key="docs/active.pdf")
        deleted = DocumentFactory(r2_key="docs/deleted.pdf")
        soft_delete_document(document=deleted, actor=actor)
        result = get_document_list()
        assert result.count() == 1
        assert result.first().pk == active.pk

    def test_no_filters_returns_all_active(self, db):
        DocumentFactory.create_batch(3)
        assert get_document_list(filters=None).count() == 3

    def test_filter_by_contact_id(self, db):
        contact = ContactFactory()
        DocumentFactory(contact=contact, r2_key="docs/contact_doc.pdf")
        DocumentFactory(r2_key="docs/other.pdf")  # contacto distinto
        result = get_document_list(filters=DocumentFilters(contact_id=contact.pk))
        assert result.count() == 1

    def test_filter_by_property_id(self, db):
        prop = PropertyFactory()
        doc_with_prop = DocumentFactory(
            property=prop,
            r2_key="docs/prop_doc.pdf",
        )
        DocumentFactory(r2_key="docs/other.pdf")  # sin propiedad
        result = get_document_list(filters=DocumentFilters(property_id=prop.pk))
        assert result.count() == 1
        assert result.first().pk == doc_with_prop.pk

    def test_combined_filters_apply_as_and(self, db):
        contact = ContactFactory()
        prop = PropertyFactory()
        both = DocumentFactory(
            contact=contact,
            property=prop,
            r2_key="docs/both.pdf",
        )
        DocumentFactory(
            contact=contact,
            r2_key="docs/contact_only.pdf",
        )
        DocumentFactory(
            contact=None,
            property=prop,
            r2_key="docs/prop_only.pdf",
        )
        result = get_document_list(
            filters=DocumentFilters(
                contact_id=contact.pk,
                property_id=prop.pk,
            )
        )
        assert result.count() == 1
        assert result.first().pk == both.pk

    def test_select_related_no_extra_queries(self, db, django_assert_num_queries):
        DocumentFactory()
        docs = list(get_document_list())
        with django_assert_num_queries(0):
            for doc in docs:
                _ = doc.contact.full_name if doc.contact else None
                _ = doc.created_by.username if doc.created_by else None


class TestGetDocumentDetail:
    def test_returns_document(self, db):
        doc = DocumentFactory()
        result = get_document_detail(doc.pk)
        assert result.pk == doc.pk

    def test_raises_if_not_found(self, db):
        with pytest.raises(Document.DoesNotExist):
            get_document_detail(uuid.uuid4())

    def test_raises_if_soft_deleted(self, db, actor):
        doc = DocumentFactory()
        soft_delete_document(document=doc, actor=actor)
        with pytest.raises(Document.DoesNotExist):
            get_document_detail(doc.pk)


class TestGetDeletedDocuments:
    def test_returns_only_soft_deleted(self, db, actor):
        DocumentFactory(r2_key="docs/active.pdf")
        deleted = DocumentFactory(r2_key="docs/deleted.pdf")
        soft_delete_document(document=deleted, actor=actor)
        result = get_deleted_documents()
        assert result.count() == 1
        assert result.first().pk == deleted.pk

    def test_excludes_active_documents(self, db):
        DocumentFactory.create_batch(3)
        assert get_deleted_documents().count() == 0

    def test_filter_by_property_id_in_deleted(self, db, actor):
        prop = PropertyFactory()
        doc_with_prop = DocumentFactory(
            property=prop,
            r2_key="docs/prop.pdf",
        )
        doc_other = DocumentFactory(r2_key="docs/other.pdf")
        soft_delete_document(document=doc_with_prop, actor=actor)
        soft_delete_document(document=doc_other, actor=actor)
        result = get_deleted_documents(
            filters=DocumentFilters(property_id=prop.pk)
        )
        assert result.count() == 1
        assert result.first().pk == doc_with_prop.pk