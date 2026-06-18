import uuid
from datetime import date

import pytest

from apps.contacts.tests.factories import ContactFactory, UserFactory
from apps.deals.choices import DealOutcome, DealType
from apps.deals.models import Deal
from apps.deals.selectors import (
    DealFilters,
    get_deal_detail,
    get_deal_list,
    get_open_deals_for_contact,
    get_open_deals_for_listing,
)
from apps.deals.tests.factories import DealFactory
from apps.listings.tests.factories import ListingFactory
from apps.properties.tests.factories import PropertyFactory


@pytest.mark.django_db
class TestGetOpenDealsForContact:
    def test_returns_open_deal_for_contact(self):
        contact = ContactFactory()
        deal = DealFactory(client_contact=contact, outcome="")
        assert deal in get_open_deals_for_contact(contact.pk)

    def test_excludes_closed_deal(self):
        contact = ContactFactory()
        DealFactory(client_contact=contact, outcome=DealOutcome.WON)
        assert get_open_deals_for_contact(contact.pk).count() == 0

    def test_excludes_deals_from_other_contacts(self):
        contact = ContactFactory()
        other = ContactFactory()
        DealFactory(client_contact=other, outcome="")
        assert get_open_deals_for_contact(contact.pk).count() == 0

    def test_excludes_soft_deleted_deal(self):
        actor = UserFactory()
        contact = ContactFactory()
        deal = DealFactory(client_contact=contact, outcome="", created_by=actor, updated_by=actor)
        deal.soft_delete(actor=actor)
        assert get_open_deals_for_contact(contact.pk).count() == 0


@pytest.mark.django_db
class TestGetOpenDealsForListing:
    def test_returns_open_deal_for_listing(self):
        listing = ListingFactory()
        contact = ContactFactory()
        deal = DealFactory.create(with_listing=True, listing=listing, client_contact=contact, outcome="")
        assert deal in get_open_deals_for_listing(listing.pk)

    def test_excludes_closed_deal(self):
        listing = ListingFactory()
        contact = ContactFactory()
        DealFactory.create(with_listing=True, listing=listing, client_contact=contact, outcome=DealOutcome.LOST)
        assert get_open_deals_for_listing(listing.pk).count() == 0

    def test_excludes_deals_from_other_listings(self):
        listing = ListingFactory()
        other_listing = ListingFactory()
        contact = ContactFactory()
        DealFactory.create(with_listing=True, listing=other_listing, client_contact=contact, outcome="")
        assert get_open_deals_for_listing(listing.pk).count() == 0


@pytest.mark.django_db
class TestGetDealList:
    def test_returns_all_deals_without_filters(self):
        deal = DealFactory()
        assert deal in get_deal_list()

    def test_filters_by_deal_type(self):
        contact = ContactFactory()
        rent = DealFactory(deal_type=DealType.RENT, client_contact=contact)
        sale = DealFactory(deal_type=DealType.SALE, client_contact=contact)
        qs = get_deal_list(DealFilters(deal_type=DealType.RENT))
        assert rent in qs
        assert sale not in qs

    def test_filters_by_outcome(self):
        won = DealFactory(outcome=DealOutcome.WON)
        open_ = DealFactory(outcome="")
        qs = get_deal_list(DealFilters(outcome=DealOutcome.WON))
        assert won in qs
        assert open_ not in qs

    def test_filters_by_agent(self):
        agent = UserFactory()
        with_agent = DealFactory(agent=agent)
        without_agent = DealFactory(agent=None)
        qs = get_deal_list(DealFilters(agent_id=agent.pk))
        assert with_agent in qs
        assert without_agent not in qs

    def test_filters_by_client_contact(self):
        contact = ContactFactory()
        other = ContactFactory()
        deal = DealFactory(client_contact=contact)
        other_deal = DealFactory(client_contact=other)
        qs = get_deal_list(DealFilters(client_contact_id=contact.pk))
        assert deal in qs
        assert other_deal not in qs

    def test_filters_by_listing(self):
        listing = ListingFactory()
        other_listing = ListingFactory()
        deal = DealFactory.create(with_listing=True, listing=listing)
        other_deal = DealFactory.create(with_listing=True, listing=other_listing)
        qs = get_deal_list(DealFilters(listing_id=listing.pk))
        assert deal in qs
        assert other_deal not in qs

    def test_is_open_true_returns_only_open_deals(self):
        open_ = DealFactory(outcome="")
        closed = DealFactory(outcome=DealOutcome.CANCELLED)
        qs = get_deal_list(DealFilters(is_open=True))
        assert open_ in qs
        assert closed not in qs

    def test_is_open_false_returns_only_closed_deals(self):
        open_ = DealFactory(outcome="")
        closed = DealFactory(outcome=DealOutcome.LOST)
        qs = get_deal_list(DealFilters(is_open=False))
        assert open_ not in qs
        assert closed in qs

    def test_filters_by_expected_close_before(self):
        soon = DealFactory(outcome="", expected_close_date=date(2025, 1, 15))
        later = DealFactory(outcome="", expected_close_date=date(2025, 6, 1))
        qs = get_deal_list(DealFilters(expected_close_before=date(2025, 3, 1)))
        assert soon in qs
        assert later not in qs

    def test_excludes_soft_deleted_deals(self):
        actor = UserFactory()
        deal = DealFactory(created_by=actor, updated_by=actor)
        deal.soft_delete(actor=actor)
        assert deal not in get_deal_list()


@pytest.mark.django_db
class TestGetDealDetail:
    def test_returns_deal_with_related_objects(self):
        deal = DealFactory.create(with_listing=True)
        result = get_deal_detail(deal.pk)
        assert result.client_contact is not None
        assert result.listing is not None
        assert result.listing.property is not None

    def test_raises_does_not_exist_for_unknown_id(self):
        with pytest.raises(Deal.DoesNotExist):
            get_deal_detail(uuid.uuid4())

    def test_raises_does_not_exist_for_soft_deleted_deal(self):
        actor = UserFactory()
        deal = DealFactory(created_by=actor, updated_by=actor)
        deal.soft_delete(actor=actor)
        with pytest.raises(Deal.DoesNotExist):
            get_deal_detail(deal.pk)