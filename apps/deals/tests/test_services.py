from datetime import date

import pytest

from apps.contacts.tests.factories import ContactFactory, UserFactory
from apps.deals.choices import DealOutcome, DealType
from apps.deals.exceptions import DealAlreadyClosed, DealValidationError
from apps.deals.models import Deal
from apps.deals.services import archive_deal, close_deal, create_deal, update_deal
from apps.deals.tests.factories import DealFactory
from apps.listings.tests.factories import ListingFactory
from apps.listings.choices import ListingStatus, OperationType 
from apps.properties.choices import PropertyStatus
from apps.properties.tests.factories import PropertyFactory


@pytest.mark.django_db
class TestCreateDeal:
    def test_create_deal_with_listing(self):
        actor = UserFactory()
        contact = ContactFactory()
        listing = ListingFactory()
        deal = create_deal(
            deal_type=DealType.RENT,
            client_contact_id=contact.pk,
            listing_id=listing.pk,
            actor=actor,
        )
        assert deal.pk is not None
        assert deal.listing_id == listing.pk
        assert deal.outcome == ""
        assert deal.created_by == actor
        assert deal.updated_by == actor

    def test_create_deal_with_external_notes(self):
        actor = UserFactory()
        contact = ContactFactory()
        deal = create_deal(
            deal_type=DealType.SALE,
            client_contact_id=contact.pk,
            external_property_notes="Propiedad de otra inmobiliaria.",
            actor=actor,
        )
        assert deal.listing_id is None
        assert deal.external_property_notes == "Propiedad de otra inmobiliaria."

    def test_create_deal_raises_without_listing_and_notes(self):
        actor = UserFactory()
        contact = ContactFactory()
        with pytest.raises(DealValidationError):
            create_deal(
                deal_type=DealType.RENT,
                client_contact_id=contact.pk,
                actor=actor,
            )

    def test_create_deal_assigns_agent_when_provided(self):
        actor = UserFactory()
        agent = UserFactory()
        contact = ContactFactory()
        listing = ListingFactory()
        deal = create_deal(
            deal_type=DealType.RENT,
            client_contact_id=contact.pk,
            listing_id=listing.pk,
            agent_id=agent.pk,
            actor=actor,
        )
        assert deal.agent_id == agent.pk

    def test_create_deal_has_no_agent_by_default(self):
        actor = UserFactory()
        contact = ContactFactory()
        listing = ListingFactory()
        deal = create_deal(
            deal_type=DealType.RENT,
            client_contact_id=contact.pk,
            listing_id=listing.pk,
            actor=actor,
        )
        assert deal.agent_id is None


@pytest.mark.django_db
class TestUpdateDeal:
    def test_update_deal_updates_notes(self):
        actor = UserFactory()
        deal = DealFactory(created_by=actor, updated_by=actor)
        update_deal(deal=deal, notes="Nota actualizada.", actor=actor)
        deal.refresh_from_db()
        assert deal.notes == "Nota actualizada."

    def test_update_deal_assigns_agent(self):
        actor = UserFactory()
        agent = UserFactory()
        deal = DealFactory(created_by=actor, updated_by=actor)
        update_deal(deal=deal, agent_id=agent.pk, actor=actor)
        deal.refresh_from_db()
        assert deal.agent_id == agent.pk

    def test_update_deal_clears_agent_with_none(self):
        actor = UserFactory()
        deal = DealFactory(agent=actor, created_by=actor, updated_by=actor)
        update_deal(deal=deal, agent_id=None, actor=actor)
        deal.refresh_from_db()
        assert deal.agent_id is None

    def test_update_deal_clears_expected_close_date_with_none(self):
        actor = UserFactory()
        deal = DealFactory(
            expected_close_date=date(2025, 12, 31),
            created_by=actor,
            updated_by=actor,
        )
        update_deal(deal=deal, expected_close_date=None, actor=actor)
        deal.refresh_from_db()
        assert deal.expected_close_date is None

    def test_update_deal_unset_fields_are_not_modified(self):
        actor = UserFactory()
        deal = DealFactory(notes="original", agent=None, created_by=actor, updated_by=actor)
        update_deal(deal=deal, actor=actor)
        deal.refresh_from_db()
        assert deal.notes == "original"
        assert deal.agent_id is None

    def test_update_deal_always_sets_updated_by(self):
        original_actor = UserFactory()
        new_actor = UserFactory()
        deal = DealFactory(created_by=original_actor, updated_by=original_actor)
        update_deal(deal=deal, notes="x", actor=new_actor)
        deal.refresh_from_db()
        assert deal.updated_by == new_actor


@pytest.mark.django_db
class TestCloseDeal:
    def test_close_deal_as_won(self):
        actor = UserFactory()
        deal = DealFactory(outcome="", created_by=actor, updated_by=actor)
        close_deal(deal=deal, outcome=DealOutcome.WON, actor=actor)
        deal.refresh_from_db()
        assert deal.outcome == DealOutcome.WON
        assert deal.closed_at is not None

    def test_close_deal_as_lost(self):
        actor = UserFactory()
        deal = DealFactory(outcome="", created_by=actor, updated_by=actor)
        close_deal(deal=deal, outcome=DealOutcome.LOST, actor=actor)
        deal.refresh_from_db()
        assert deal.outcome == DealOutcome.LOST

    def test_close_deal_as_cancelled(self):
        actor = UserFactory()
        deal = DealFactory(outcome="", created_by=actor, updated_by=actor)
        close_deal(deal=deal, outcome=DealOutcome.CANCELLED, actor=actor)
        deal.refresh_from_db()
        assert deal.outcome == DealOutcome.CANCELLED

    def test_close_deal_won_rent_updates_property_to_rented(self):
        actor = UserFactory()
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        listing = ListingFactory(property=prop)
        deal = DealFactory.create(
            with_listing=True,
            listing=listing,
            deal_type=DealType.RENT,
            outcome="",
            created_by=actor,
            updated_by=actor,
        )
        close_deal(deal=deal, outcome=DealOutcome.WON, actor=actor)
        prop.refresh_from_db()
        assert prop.status == PropertyStatus.RENTED

    def test_close_deal_won_sale_updates_property_to_sold(self):
        actor = UserFactory()
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        listing = ListingFactory(property=prop)
        deal = DealFactory.create(
            with_listing=True,
            listing=listing,
            deal_type=DealType.SALE,
            outcome="",
            created_by=actor,
            updated_by=actor,
        )
        close_deal(deal=deal, outcome=DealOutcome.WON, actor=actor)
        prop.refresh_from_db()
        assert prop.status == PropertyStatus.SOLD

    def test_close_deal_won_without_listing_does_not_raise(self):
        actor = UserFactory()
        deal = DealFactory(
            listing=None,
            external_property_notes="Propiedad ajena.",
            deal_type=DealType.RENT,
            outcome="",
            created_by=actor,
            updated_by=actor,
        )
        # No hay propiedad que actualizar — no debe lanzar
        closed = close_deal(deal=deal, outcome=DealOutcome.WON, actor=actor)
        assert closed.outcome == DealOutcome.WON

    def test_close_deal_lost_does_not_update_property_status(self):
        actor = UserFactory()
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        listing = ListingFactory(property=prop)
        deal = DealFactory.create(
            with_listing=True,
            listing=listing,
            outcome="",
            created_by=actor,
            updated_by=actor,
        )
        close_deal(deal=deal, outcome=DealOutcome.LOST, actor=actor)
        prop.refresh_from_db()
        assert prop.status == PropertyStatus.AVAILABLE

    def test_close_deal_raises_if_already_closed(self):
        actor = UserFactory()
        deal = DealFactory(outcome="", created_by=actor, updated_by=actor)
        close_deal(deal=deal, outcome=DealOutcome.WON, actor=actor)
        with pytest.raises(DealAlreadyClosed):
            close_deal(deal=deal, outcome=DealOutcome.LOST, actor=actor)


@pytest.mark.django_db
class TestArchiveDeal:
    def test_archive_open_deal(self):
        actor = UserFactory()
        deal = DealFactory(outcome="", created_by=actor, updated_by=actor)
        archive_deal(deal=deal, actor=actor)
        deal.refresh_from_db()
        assert deal.deleted_at is not None

    def test_archive_closed_deal(self):
        actor = UserFactory()
        deal = DealFactory(outcome=DealOutcome.LOST, created_by=actor, updated_by=actor)
        archive_deal(deal=deal, actor=actor)
        deal.refresh_from_db()
        assert deal.deleted_at is not None

    def test_archive_deal_sets_updated_by(self):
        actor = UserFactory()
        deal = DealFactory(created_by=actor, updated_by=actor)
        archive_deal(deal=deal, actor=actor)
        deal.refresh_from_db()
        assert deal.updated_by == actor

    def test_archived_deal_excluded_from_default_manager(self):
        actor = UserFactory()
        deal = DealFactory(created_by=actor, updated_by=actor)
        archive_deal(deal=deal, actor=actor)
        assert not Deal.objects.filter(pk=deal.pk).exists()

    def test_archived_deal_accessible_via_all_objects(self):
        actor = UserFactory()
        deal = DealFactory(created_by=actor, updated_by=actor)
        archive_deal(deal=deal, actor=actor)
        assert Deal.all_objects.filter(pk=deal.pk).exists()


@pytest.mark.django_db
class TestCloseDealListingReconciliation:
    """
    Wiring: close_deal enruta por operations.transition_property_status, que
    reconcilia los listings. Estos tests prueban que el efecto llega en la
    integración; el detalle de la cascada vive en apps/operations/tests.
    """

    def test_won_sale_closes_sale_and_pauses_rent(self):
        actor = UserFactory()
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        sale = ListingFactory(
            property=prop,
            operation_type=OperationType.SALE,
            status=ListingStatus.PUBLISHED,
        )
        rent = ListingFactory(
            property=prop,
            operation_type=OperationType.RENT,
            status=ListingStatus.PUBLISHED,
        )
        deal = DealFactory.create(
            with_listing=True,
            listing=sale,
            deal_type=DealType.SALE,
            outcome="",
            created_by=actor,
            updated_by=actor,
        )
        close_deal(deal=deal, outcome=DealOutcome.WON, actor=actor)
        sale.refresh_from_db()
        rent.refresh_from_db()
        assert sale.status == ListingStatus.CLOSED
        assert rent.status == ListingStatus.PAUSED

    def test_won_rent_closes_rent_and_leaves_sale(self):
        actor = UserFactory()
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        sale = ListingFactory(
            property=prop,
            operation_type=OperationType.SALE,
            status=ListingStatus.PUBLISHED,
        )
        rent = ListingFactory(
            property=prop,
            operation_type=OperationType.RENT,
            status=ListingStatus.PUBLISHED,
        )
        deal = DealFactory.create(
            with_listing=True,
            listing=rent,
            deal_type=DealType.RENT,
            outcome="",
            created_by=actor,
            updated_by=actor,
        )
        close_deal(deal=deal, outcome=DealOutcome.WON, actor=actor)
        sale.refresh_from_db()
        rent.refresh_from_db()
        assert rent.status == ListingStatus.CLOSED
        assert sale.status == ListingStatus.PUBLISHED

    def test_won_sale_on_rented_keeps_rented(self):
        # precedencia: vender una unidad alquilada cierra el listing de venta
        # pero mantiene RENTED — la ocupación gana sobre el evento de venta.
        actor = UserFactory()
        prop = PropertyFactory(status=PropertyStatus.RENTED)
        sale = ListingFactory(
            property=prop,
            operation_type=OperationType.SALE,
            status=ListingStatus.PUBLISHED,
        )
        rent = ListingFactory(
            property=prop,
            operation_type=OperationType.RENT,
            status=ListingStatus.PUBLISHED,
        )
        deal = DealFactory.create(
            with_listing=True,
            listing=sale,
            deal_type=DealType.SALE,
            outcome="",
            created_by=actor,
            updated_by=actor,
        )
        close_deal(deal=deal, outcome=DealOutcome.WON, actor=actor)
        prop.refresh_from_db()
        sale.refresh_from_db()
        rent.refresh_from_db()
        assert prop.status == PropertyStatus.RENTED
        assert sale.status == ListingStatus.CLOSED
        assert rent.status == ListingStatus.PUBLISHED