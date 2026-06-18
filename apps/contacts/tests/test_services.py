# apps/contacts/tests/test_services.py
import pytest

from apps.contacts.exceptions import ContactHasOpenDeals
from apps.contacts.tests.factories import ContactFactory, UserFactory
from apps.contacts.models import Contact
from apps.contacts.services import (
    archive_contact,
    create_contact,
    restore_contact,
    update_contact,
)
from apps.deals.tests.factories import DealFactory


@pytest.mark.django_db
class TestCreateContact:
    def test_creates_contact_with_required_fields(self):
        actor = UserFactory()
        contact = create_contact(full_name="Juan Perez", actor=actor)

        assert contact.pk is not None
        assert contact.full_name == "Juan Perez"
        assert contact.deleted_at is None

    def test_assigns_actor_as_created_by(self):
        actor = UserFactory()
        contact = create_contact(full_name="Juan Perez", actor=actor)

        assert contact.created_by == actor
        assert contact.updated_by == actor

    def test_creates_contact_with_optional_fields(self):
        actor = UserFactory()
        agent = UserFactory()
        contact = create_contact(
            full_name="Juan Perez",
            email="juan@email.com",
            phone="3624000000",
            assigned_agent=agent,
            actor=actor,
        )

        assert contact.email == "juan@email.com"
        assert contact.assigned_agent == agent


@pytest.mark.django_db
class TestUpdateContact:
    def test_updates_fields(self):
        actor = UserFactory()
        contact = ContactFactory()

        updated = update_contact(
            contact,
            full_name="Nombre Nuevo",
            contact_type=contact.contact_type,
            email="nuevo@email.com",
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

        assert updated.full_name == "Nombre Nuevo"
        assert updated.email == "nuevo@email.com"
        assert updated.updated_by == actor

    def test_updated_at_changes(self):
        actor = UserFactory()
        contact = ContactFactory()
        original_updated_at = contact.updated_at

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

        contact.refresh_from_db()
        assert contact.updated_at > original_updated_at


@pytest.mark.django_db
class TestArchiveContact:
    def test_archives_contact_without_open_deals(self):
        actor = UserFactory()
        contact = ContactFactory()

        archive_contact(contact, actor=actor)

        contact.refresh_from_db()
        assert contact.deleted_at is not None

    def test_raises_with_open_deals(self):
        actor = UserFactory()
        contact = ContactFactory()
        DealFactory(client_contact=contact, outcome="")

        with pytest.raises(ContactHasOpenDeals):
            archive_contact(contact, actor=actor)

    def test_allows_archive_with_closed_deal(self):
        actor = UserFactory()
        contact = ContactFactory()
        DealFactory(client_contact=contact, outcome="won")

        archive_contact(contact, actor=actor)  # no debe lanzar

        contact.refresh_from_db()
        assert contact.deleted_at is not None


@pytest.mark.django_db
class TestRestoreContact:
    def test_restores_archived_contact(self):
        actor = UserFactory()
        contact = ContactFactory()
        contact.soft_delete(actor=actor)

        restore_contact(contact, actor=actor)

        contact.refresh_from_db()
        assert contact.deleted_at is None

    def test_restored_contact_visible_in_default_manager(self):
        actor = UserFactory()
        contact = ContactFactory()
        contact.soft_delete(actor=actor)

        restore_contact(contact, actor=actor)

        assert Contact.objects.filter(pk=contact.pk).exists()