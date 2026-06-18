import pytest

from apps.audit.models import AuditLog, AuditAction
from apps.contacts.tests.factories import ContactFactory, UserFactory
from apps.contacts.models import Contact
from apps.contacts.services import (
    create_contact,
    update_contact,
    archive_contact,
    restore_contact,
)


@pytest.mark.django_db
class TestAuditSignalOnCreate:
    def test_create_generates_audit_log(self):
        actor = UserFactory()
        create_contact(full_name="Juan Perez", actor=actor)

        assert AuditLog.objects.filter(
            entity_type="Contact",
            action=AuditAction.CREATE,
        ).exists()

    def test_create_before_is_null(self):
        actor = UserFactory()
        contact = create_contact(full_name="Juan Perez", actor=actor)

        log = AuditLog.objects.get(entity_type="Contact", entity_id=contact.pk)
        assert log.before is None

    def test_create_after_contains_full_name(self):
        actor = UserFactory()
        contact = create_contact(full_name="Juan Perez", actor=actor)

        log = AuditLog.objects.get(entity_type="Contact", entity_id=contact.pk)
        assert log.after["full_name"] == "Juan Perez"

    def test_create_actor_id_matches_actor(self):
        actor = UserFactory()
        contact = create_contact(full_name="Juan Perez", actor=actor)

        log = AuditLog.objects.get(entity_type="Contact", entity_id=contact.pk)
        assert str(log.actor_id) == str(actor.pk)


@pytest.mark.django_db
class TestAuditSignalOnUpdate:
    def test_update_generates_audit_log(self):
        actor = UserFactory()
        contact = ContactFactory()

        update_contact(
            contact,
            full_name="Nombre Nuevo",
            contact_type=contact.contact_type,
            email=contact.email,
            phone=contact.phone,
            document_type=contact.document_type,
            document_number=contact.document_number,
            role=contact.role,
            source=contact.source,
            source_detail=contact.source_detail,
            assigned_agent=contact.assigned_agent,
            notes=contact.notes,
            actor=actor,
        )

        assert AuditLog.objects.filter(
            entity_type="Contact",
            entity_id=contact.pk,
            action=AuditAction.UPDATE,
        ).exists()

    def test_update_captures_before_and_after(self):
        actor = UserFactory()
        contact = ContactFactory(full_name="Nombre Original")

        update_contact(
            contact,
            full_name="Nombre Nuevo",
            contact_type=contact.contact_type,
            email=contact.email,
            phone=contact.phone,
            document_type=contact.document_type,
            document_number=contact.document_number,
            role=contact.role,
            source=contact.source,
            source_detail=contact.source_detail,
            assigned_agent=contact.assigned_agent,
            notes=contact.notes,
            actor=actor,
        )

        log = AuditLog.objects.get(
            entity_type="Contact",
            entity_id=contact.pk,
            action=AuditAction.UPDATE,
        )
        assert log.before["full_name"] == "Nombre Original"
        assert log.after["full_name"] == "Nombre Nuevo"

    def test_update_actor_id_matches_actor(self):
        actor = UserFactory()
        contact = ContactFactory()

        update_contact(
            contact,
            full_name="Nombre Nuevo",
            contact_type=contact.contact_type,
            email=contact.email,
            phone=contact.phone,
            document_type=contact.document_type,
            document_number=contact.document_number,
            role=contact.role,
            source=contact.source,
            source_detail=contact.source_detail,
            assigned_agent=contact.assigned_agent,
            notes=contact.notes,
            actor=actor,
        )

        log = AuditLog.objects.get(
            entity_type="Contact",
            entity_id=contact.pk,
            action=AuditAction.UPDATE,
        )
        assert str(log.actor_id) == str(actor.pk)


@pytest.mark.django_db
class TestAuditSignalOnSoftDelete:
    def test_archive_generates_delete_action(self):
        actor = UserFactory()
        contact = ContactFactory()

        archive_contact(contact, actor=actor)

        assert AuditLog.objects.filter(
            entity_type="Contact",
            entity_id=contact.pk,
            action=AuditAction.DELETE,
        ).exists()

    def test_archive_before_has_null_deleted_at(self):
        actor = UserFactory()
        contact = ContactFactory()

        archive_contact(contact, actor=actor)

        log = AuditLog.objects.get(
            entity_type="Contact",
            entity_id=contact.pk,
            action=AuditAction.DELETE,
        )
        assert log.before["deleted_at"] is None

    def test_archive_after_has_deleted_at_set(self):
        actor = UserFactory()
        contact = ContactFactory()

        archive_contact(contact, actor=actor)

        log = AuditLog.objects.get(
            entity_type="Contact",
            entity_id=contact.pk,
            action=AuditAction.DELETE,
        )
        assert log.after["deleted_at"] is not None


@pytest.mark.django_db
class TestAuditSignalOnRestore:
    def test_restore_generates_restore_action(self):
        actor = UserFactory()
        contact = ContactFactory()
        contact.soft_delete(actor=actor)

        restore_contact(contact, actor=actor)

        assert AuditLog.objects.filter(
            entity_type="Contact",
            entity_id=contact.pk,
            action=AuditAction.RESTORE,
        ).exists()

    def test_restore_before_has_deleted_at_set(self):
        actor = UserFactory()
        contact = ContactFactory()
        contact.soft_delete(actor=actor)

        restore_contact(contact, actor=actor)

        log = AuditLog.objects.get(
            entity_type="Contact",
            entity_id=contact.pk,
            action=AuditAction.RESTORE,
        )
        assert log.before["deleted_at"] is not None

    def test_restore_after_has_null_deleted_at(self):
        actor = UserFactory()
        contact = ContactFactory()
        contact.soft_delete(actor=actor)

        restore_contact(contact, actor=actor)

        log = AuditLog.objects.get(
            entity_type="Contact",
            entity_id=contact.pk,
            action=AuditAction.RESTORE,
        )
        assert log.after["deleted_at"] is None


@pytest.mark.django_db
class TestAuditSignalNotFiredForInfrastructure:
    def test_search_preference_does_not_generate_audit_log(self):
        """
        SearchPreference hereda TimestampModel — no es AuditableMixin.
        Crear una preferencia no debe generar entradas en AuditLog.
        """
        from apps.contacts.models import SearchPreference
        from apps.listings.choices import OperationType

        contact = ContactFactory()
        SearchPreference.objects.create(
            contact=contact,
            operation_type=OperationType.RENT,
        )

        assert not AuditLog.objects.filter(entity_type="SearchPreference").exists()