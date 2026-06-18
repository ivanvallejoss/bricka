import pytest

from apps.contacts.tests.factories import ContactFactory
from apps.documents.exceptions import DocumentValidationError
from apps.documents.models import Document
from apps.documents.services import (
    DocumentUploadItem,
    hard_delete_document,
    soft_delete_document,
    upload_documents,
)
from apps.documents.tests.factories import DocumentFactory
from apps.properties.tests.factories import PropertyFactory


class TestUploadDocuments:
    def test_uploads_single_document(self, db, actor):
        prop = PropertyFactory()
        items = [
            DocumentUploadItem(
                r2_key="docs/test.pdf",
                original_filename="test.pdf",
                content_type="application/pdf",
                file_size=1024,
            )
        ]
        docs = upload_documents(items=items, property_id=prop.pk, actor=actor)
        assert len(docs) == 1
        assert Document.objects.count() == 1

    def test_uploads_multiple_documents_atomically(self, db, actor):
        prop = PropertyFactory()
        items = [
            DocumentUploadItem(
                r2_key=f"docs/test_{i}.pdf",
                original_filename=f"test_{i}.pdf",
                content_type="application/pdf",
                file_size=1024,
            )
            for i in range(3)
        ]
        docs = upload_documents(items=items, property_id=prop.pk, actor=actor)
        assert len(docs) == 3
        assert Document.objects.count() == 3

    def test_assigns_actor_as_created_by(self, db, actor):
        prop = PropertyFactory()
        items = [
            DocumentUploadItem(
                r2_key="docs/test.pdf",
                original_filename="test.pdf",
                content_type="application/pdf",
                file_size=1024,
            )
        ]
        docs = upload_documents(items=items, property_id=prop.pk, actor=actor)
        assert docs[0].created_by == actor
        assert docs[0].updated_by == actor

    def test_raises_without_any_parent_entity(self, db, actor):
        items = [
            DocumentUploadItem(
                r2_key="docs/test.pdf",
                original_filename="test.pdf",
                content_type="application/pdf",
                file_size=1024,
            )
        ]
        with pytest.raises(DocumentValidationError):
            upload_documents(items=items, actor=actor)

    def test_raises_with_empty_items_list(self, db, actor):
        prop = PropertyFactory()
        with pytest.raises(DocumentValidationError):
            upload_documents(items=[], property_id=prop.pk, actor=actor)

    def test_associates_multiple_entities_simultaneously(self, db, actor):
        contact = ContactFactory()
        prop = PropertyFactory()
        items = [
            DocumentUploadItem(
                r2_key="docs/escritura.pdf",
                original_filename="escritura.pdf",
                content_type="application/pdf",
                file_size=2048,
            )
        ]
        docs = upload_documents(
            items=items,
            contact_id=contact.pk,
            property_id=prop.pk,
            actor=actor,
        )
        doc = docs[0]
        assert doc.contact_id == contact.pk
        assert doc.property_id == prop.pk

    def test_each_item_persists_own_description(self, db, actor):
        prop = PropertyFactory()
        items = [
            DocumentUploadItem(
                r2_key="docs/escritura.pdf",
                original_filename="escritura.pdf",
                content_type="application/pdf",
                file_size=1024,
                description="Escritura",
            ),
            DocumentUploadItem(
                r2_key="docs/dni.pdf",
                original_filename="dni.pdf",
                content_type="application/pdf",
                file_size=512,
                description="DNI propietario",
            ),
        ]
        docs = upload_documents(items=items, property_id=prop.pk, actor=actor)
        assert docs[0].description == "Escritura"
        assert docs[1].description == "DNI propietario"

    def test_rollback_if_batch_fails(self, db, actor):
        """
        r2_key duplicado dispara IntegrityError en el segundo save.
        transaction.atomic() garantiza rollback del primer save también.
        """
        prop = PropertyFactory()
        items = [
            DocumentUploadItem(
                r2_key="docs/duplicado.pdf",
                original_filename="a.pdf",
                content_type="application/pdf",
                file_size=1024,
            ),
            DocumentUploadItem(
                r2_key="docs/duplicado.pdf",  # duplicado → IntegrityError
                original_filename="b.pdf",
                content_type="application/pdf",
                file_size=512,
            ),
        ]
        with pytest.raises(Exception):
            upload_documents(items=items, property_id=prop.pk, actor=actor)
        assert Document.objects.count() == 0


class TestSoftDeleteDocument:
    def test_soft_deletes_document(self, db, actor):
        doc = DocumentFactory()
        soft_delete_document(document=doc, actor=actor)
        assert doc.deleted_at is not None

    def test_soft_deleted_excluded_from_default_manager(self, db, actor):
        doc = DocumentFactory()
        soft_delete_document(document=doc, actor=actor)
        assert not Document.objects.filter(pk=doc.pk).exists()

    def test_soft_deleted_visible_in_all_objects(self, db, actor):
        doc = DocumentFactory()
        soft_delete_document(document=doc, actor=actor)
        assert Document.all_objects.filter(pk=doc.pk).exists()


class TestHardDeleteDocument:
    def test_hard_delete_removes_soft_deleted_document(self, db, actor):
        """
        Flujo esperado desde la papelera:
        soft_delete primero → hard_delete desde la vista de papelera.
        """
        doc = DocumentFactory()
        doc_pk = doc.pk
        soft_delete_document(document=doc, actor=actor)
        hard_delete_document(document=doc)
        assert not Document.all_objects.filter(pk=doc_pk).exists()

    def test_hard_delete_leaves_no_trace(self, db, actor):
        """
        Después del hard delete el registro desaparece de all_objects —
        no es un soft delete disfrazado.
        """
        doc = DocumentFactory()
        doc_pk = doc.pk
        soft_delete_document(document=doc, actor=actor)
        hard_delete_document(document=doc)
        assert Document.all_objects.filter(pk=doc_pk).count() == 0