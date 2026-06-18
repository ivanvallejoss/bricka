import pytest

from apps.audit.models import AuditLog, AuditAction
from apps.contacts.choices import ContactRole, ContactSource
from apps.contacts.tests.factories import ContactFactory, UserFactory
from apps.contacts.models import Contact
from apps.contacts.selectors import (
    ContactFilters,
    get_contact_detail,
    get_contact_history,
    get_contact_list,
)
from apps.contacts.services import (
    archive_contact,
    create_contact,
    update_contact,
)


@pytest.mark.django_db
class TestGetContactList:
    def test_returns_active_contacts(self):
        ContactFactory.create_batch(3)
        result = get_contact_list()
        assert result.count() == 3

    def test_excludes_archived_contacts(self):
        actor = UserFactory()
        active = ContactFactory()
        archived = ContactFactory()
        archived.soft_delete(actor=actor)

        result = get_contact_list()

        pks = list(result.values_list("pk", flat=True))
        assert active.pk in pks
        assert archived.pk not in pks

    def test_no_filters_returns_all_active(self):
        ContactFactory.create_batch(5)
        assert get_contact_list().count() == 5

    def test_filter_by_role(self):
        ContactFactory(role=ContactRole.OWNER)
        ContactFactory(role=ContactRole.OWNER)
        ContactFactory(role=ContactRole.TENANT)

        result = get_contact_list(filters=ContactFilters(role=ContactRole.OWNER))
        assert result.count() == 2

    def test_filter_by_source(self):
        ContactFactory(source=ContactSource.DIRECT)
        ContactFactory(source=ContactSource.DIRECT)
        ContactFactory(source=ContactSource.REFERRAL)

        result = get_contact_list(filters=ContactFilters(source=ContactSource.DIRECT))
        assert result.count() == 2

    def test_filter_by_assigned_agent(self):
        agent = UserFactory()
        ContactFactory(assigned_agent=agent)
        ContactFactory(assigned_agent=agent)
        ContactFactory(assigned_agent=None)

        result = get_contact_list(
            filters=ContactFilters(assigned_agent_id=agent.pk)
        )
        assert result.count() == 2

    def test_combined_filters(self):
        agent = UserFactory()
        ContactFactory(role=ContactRole.OWNER, assigned_agent=agent)
        ContactFactory(role=ContactRole.TENANT, assigned_agent=agent)
        ContactFactory(role=ContactRole.OWNER, assigned_agent=None)

        result = get_contact_list(
            filters=ContactFilters(
                role=ContactRole.OWNER,
                assigned_agent_id=agent.pk,
            )
        )
        assert result.count() == 1

    def test_select_related_assigned_agent_no_extra_queries(self, django_assert_num_queries):
        agent = UserFactory()
        ContactFactory.create_batch(3, assigned_agent=agent)

        with django_assert_num_queries(1):
            contacts = list(get_contact_list())
            # acceder a assigned_agent no genera queries adicionales
            for contact in contacts:
                _ = contact.assigned_agent


@pytest.mark.django_db
class TestGetContactDetail:
    def test_returns_existing_contact(self):
        contact = ContactFactory()
        result = get_contact_detail(contact.pk)
        assert result.pk == contact.pk

    def test_raises_if_not_found(self):
        import uuid
        with pytest.raises(Contact.DoesNotExist):
            get_contact_detail(uuid.uuid4())

    def test_raises_if_archived(self):
        actor = UserFactory()
        contact = ContactFactory()
        contact.soft_delete(actor=actor)

        with pytest.raises(Contact.DoesNotExist):
            get_contact_detail(contact.pk)

    def test_select_related_assigned_agent(self, django_assert_num_queries):
        agent = UserFactory()
        contact = ContactFactory(assigned_agent=agent)

        with django_assert_num_queries(1):
            result = get_contact_detail(contact.pk)
            _ = result.assigned_agent


@pytest.mark.django_db
class TestGetContactHistory:
    def test_returns_audit_logs_for_contact(self):
        actor = UserFactory()
        contact = create_contact(full_name="Juan Perez", actor=actor)

        history = get_contact_history(contact.pk)
        assert history.count() == 1

    def test_history_ordered_most_recent_first(self):
        actor = UserFactory()
        contact = ContactFactory()

        update_contact(
            contact,
            full_name="Nombre 1",
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
        update_contact(
            contact,
            full_name="Nombre 2",
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

        history = list(get_contact_history(contact.pk))
        assert history[0].after["full_name"] == "Nombre 2"
        assert history[1].after["full_name"] == "Nombre 1"

    def test_does_not_return_logs_of_other_contacts(self):
        actor = UserFactory()
        contact_a = create_contact(full_name="Contacto A", actor=actor)
        contact_b = create_contact(full_name="Contacto B", actor=actor)

        history = get_contact_history(contact_a.pk)

        entity_ids = list(history.values_list("entity_id", flat=True))
        assert all(eid == contact_a.pk for eid in entity_ids)
        assert contact_b.pk not in entity_ids

    def test_returns_empty_queryset_for_unknown_contact(self):
        import uuid
        history = get_contact_history(uuid.uuid4())
        assert history.count() == 0

    def test_history_includes_all_action_types(self):
        actor = UserFactory()
        contact = ContactFactory()

        archive_contact(contact, actor=actor)
        contact.restore(actor=actor)

        history = get_contact_history(contact.pk)
        actions = set(history.values_list("action", flat=True))

        # CREATE viene del ContactFactory, DELETE del archive, RESTORE del restore
        assert AuditAction.DELETE in actions
        assert AuditAction.RESTORE in actions