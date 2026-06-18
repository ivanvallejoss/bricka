import datetime
import uuid
from decimal import Decimal

import pytest

from apps.listings.choices import ListingStatus, OperationType, PublicationStatus
from apps.listings.models import Listing, ListingPriceHistory
from apps.listings.selectors import (
    ListingFilters,
    get_listing_detail,
    get_listing_list,
    get_listings_for_property,
    get_pending_publications,
    get_price_history_for_listing,
)
from apps.listings.tests.factories import ListingFactory, ListingPublicationFactory
from apps.contacts.tests.factories import UserFactory
from apps.properties.tests.factories import PropertyFactory
from django.utils import timezone


class TestGetListingDetail:
    def test_returns_listing(self, db):
        listing = ListingFactory()
        result = get_listing_detail(listing.pk)
        assert result.pk == listing.pk

    def test_raises_if_not_found(self, db):
        with pytest.raises(Listing.DoesNotExist):
            get_listing_detail(uuid.uuid4())

    def test_raises_if_archived(self, db, actor):
        listing = ListingFactory()
        listing.soft_delete(actor=actor)
        with pytest.raises(Listing.DoesNotExist):
            get_listing_detail(listing.pk)


class TestGetListingsForProperty:
    def test_returns_listings_for_property(self, db):
        prop = PropertyFactory()
        ListingFactory(property=prop, operation_type=OperationType.SALE)
        ListingFactory(property=prop, operation_type=OperationType.RENT)
        assert get_listings_for_property(prop.pk).count() == 2

    def test_excludes_archived_listings(self, db, actor):
        prop = PropertyFactory()
        active = ListingFactory(property=prop, operation_type=OperationType.SALE)
        archived = ListingFactory(property=prop, operation_type=OperationType.RENT)
        archived.soft_delete(actor=actor)

        result = get_listings_for_property(prop.pk)
        assert result.count() == 1
        assert result.first().pk == active.pk

    def test_isolates_by_property(self, db):
        prop_a = PropertyFactory()
        prop_b = PropertyFactory()
        ListingFactory(property=prop_a)
        ListingFactory(property=prop_b)
        assert get_listings_for_property(prop_a.pk).count() == 1


class TestGetPriceHistoryForListing:
    def test_returns_price_history(self, db, actor):
        listing = ListingFactory()
        ListingPriceHistory.objects.create(
            listing=listing,
            price=listing.price,
            currency=listing.currency,
            created_by=actor,
        )
        assert get_price_history_for_listing(listing.pk).count() == 1

    def test_ordered_most_recent_first(self, db, actor):
        listing = ListingFactory()
        old_entry = ListingPriceHistory.objects.create(
            listing=listing,
            price=Decimal("40000.00"),
            currency=listing.currency,
            created_by=actor,
        )
        # Forzamos un created_at viejo para garantizar el orden sin depender de timing
        ListingPriceHistory.objects.filter(pk=old_entry.pk).update(
            created_at=timezone.now() - datetime.timedelta(hours=1)
        )
        new_entry = ListingPriceHistory.objects.create(
            listing=listing,
            price=Decimal("50000.00"),
            currency=listing.currency,
            created_by=actor,
        )
        result = get_price_history_for_listing(listing.pk)
        assert result.first().pk == new_entry.pk

    def test_isolates_by_listing(self, db, actor):
        listing_a = ListingFactory()
        listing_b = ListingFactory()
        ListingPriceHistory.objects.create(
            listing=listing_a,
            price=listing_a.price,
            currency=listing_a.currency,
            created_by=actor,
        )
        ListingPriceHistory.objects.create(
            listing=listing_b,
            price=listing_b.price,
            currency=listing_b.currency,
            created_by=actor,
        )
        assert get_price_history_for_listing(listing_a.pk).count() == 1


class TestGetPendingPublications:
    def test_returns_pending_publications(self, db):
        ListingPublicationFactory(status=PublicationStatus.PENDING)
        ListingPublicationFactory(status=PublicationStatus.PENDING)
        assert get_pending_publications().count() == 2

    def test_excludes_non_pending(self, db):
        ListingPublicationFactory(status=PublicationStatus.PUBLISHED)
        ListingPublicationFactory(status=PublicationStatus.FAILED)
        ListingPublicationFactory(status=PublicationStatus.UNPUBLISHED)
        pending = ListingPublicationFactory(status=PublicationStatus.PENDING)

        result = get_pending_publications()
        assert result.count() == 1
        assert result.first().pk == pending.pk

    def test_select_related_no_extra_queries(self, db, django_assert_num_queries):
        ListingPublicationFactory(status=PublicationStatus.PENDING)

        # Evaluamos el queryset primero — la query se ejecuta acá
        publications = list(get_pending_publications())

        # Verificamos que acceder a listing.property no genera queries adicionales
        with django_assert_num_queries(0):
            for pub in publications:
                _ = pub.listing.property.address_line