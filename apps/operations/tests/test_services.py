import pytest

from apps.operations.services import transition_property_status
from apps.properties.choices import PropertyStatus
from apps.properties.tests.factories import PropertyFactory
from apps.listings.choices import ListingStatus, OperationType, PublicationStatus
from apps.listings.models import Listing, ListingPublication
from apps.listings.tests.factories import ListingFactory, ListingPublicationFactory


def _status(listing: Listing) -> str:
    listing.refresh_from_db()
    return listing.status


class TestTransitionToSold:
    def test_writes_property_status(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        transition_property_status(
            property=prop, new_status=PropertyStatus.SOLD, actor=actor
        )
        prop.refresh_from_db()
        assert prop.status == PropertyStatus.SOLD

    def test_closes_all_active_listings(self, db, actor):
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
        transition_property_status(
            property=prop, new_status=PropertyStatus.SOLD, actor=actor
        )
        assert _status(sale) == ListingStatus.CLOSED
        assert _status(rent) == ListingStatus.CLOSED

    def test_closes_paused_listing_too(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        rent = ListingFactory(
            property=prop,
            operation_type=OperationType.RENT,
            status=ListingStatus.PAUSED,
        )
        transition_property_status(
            property=prop, new_status=PropertyStatus.SOLD, actor=actor
        )
        assert _status(rent) == ListingStatus.CLOSED

    def test_leaves_draft_listing_untouched(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        draft = ListingFactory(
            property=prop,
            operation_type=OperationType.SALE,
            status=ListingStatus.DRAFT,
        )
        transition_property_status(
            property=prop, new_status=PropertyStatus.SOLD, actor=actor
        )
        assert _status(draft) == ListingStatus.DRAFT


class TestTransitionToRented:
    def test_closes_rent_leaves_sale(self, db, actor):
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
        transition_property_status(
            property=prop, new_status=PropertyStatus.RENTED, actor=actor
        )
        assert _status(rent) == ListingStatus.CLOSED
        assert _status(sale) == ListingStatus.PUBLISHED

    def test_closes_temporary_rent(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        temp = ListingFactory(
            property=prop,
            operation_type=OperationType.TEMPORARY_RENT,
            status=ListingStatus.PUBLISHED,
        )
        transition_property_status(
            property=prop, new_status=PropertyStatus.RENTED, actor=actor
        )
        assert _status(temp) == ListingStatus.CLOSED


class TestTransitionToUnavailable:
    def test_pauses_published_listing(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        rent = ListingFactory(
            property=prop,
            operation_type=OperationType.RENT,
            status=ListingStatus.PUBLISHED,
        )
        transition_property_status(
            property=prop, new_status=PropertyStatus.UNAVAILABLE, actor=actor
        )
        assert _status(rent) == ListingStatus.PAUSED

    def test_leaves_closed_listing_untouched(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        closed = ListingFactory(
            property=prop,
            operation_type=OperationType.SALE,
            status=ListingStatus.CLOSED,
        )
        transition_property_status(
            property=prop, new_status=PropertyStatus.UNAVAILABLE, actor=actor
        )
        assert _status(closed) == ListingStatus.CLOSED


class TestTransitionToAvailable:
    def test_unpauses_paused_listing(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.UNAVAILABLE)
        rent = ListingFactory(
            property=prop,
            operation_type=OperationType.RENT,
            status=ListingStatus.PAUSED,
        )
        transition_property_status(
            property=prop, new_status=PropertyStatus.AVAILABLE, actor=actor
        )
        assert _status(rent) == ListingStatus.PUBLISHED

    def test_leaves_closed_listing_quiet(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.SOLD)
        closed = ListingFactory(
            property=prop,
            operation_type=OperationType.SALE,
            status=ListingStatus.CLOSED,
        )
        transition_property_status(
            property=prop, new_status=PropertyStatus.AVAILABLE, actor=actor
        )
        assert _status(closed) == ListingStatus.CLOSED


class TestSystemActor:
    def test_accepts_none_actor(self, db):
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        rent = ListingFactory(
            property=prop,
            operation_type=OperationType.RENT,
            status=ListingStatus.PUBLISHED,
        )
        transition_property_status(
            property=prop, new_status=PropertyStatus.RENTED, actor=None
        )
        rent.refresh_from_db()
        assert rent.status == ListingStatus.CLOSED
        assert rent.updated_by is None


class TestExternalPublicationSurface:
    def test_surfaces_without_flipping_publication(self, db, actor, caplog):
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        listing = ListingFactory(
            property=prop,
            operation_type=OperationType.RENT,
            status=ListingStatus.PUBLISHED,
        )
        pub = ListingPublicationFactory(
            listing=listing,
            status=PublicationStatus.PUBLISHED,
        )
        with caplog.at_level("WARNING", logger="apps.operations.services"):
            transition_property_status(
                property=prop, new_status=PropertyStatus.SOLD, actor=actor
            )
        # el listing se cerró...
        listing.refresh_from_db()
        assert listing.status == ListingStatus.CLOSED
        # ...pero la publicación externa NO se tocó (avisar, no actuar)
        pub.refresh_from_db()
        assert pub.status == PublicationStatus.PUBLISHED
        # ...y se dejó registro para baja manual
        assert "listing_publication_requires_manual_takedown" in caplog.text

    def test_no_surface_when_no_published_publication(self, db, actor, caplog):
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        listing = ListingFactory(
            property=prop,
            operation_type=OperationType.RENT,
            status=ListingStatus.PUBLISHED,
        )
        ListingPublicationFactory(
            listing=listing,
            status=PublicationStatus.PENDING,
        )
        with caplog.at_level("WARNING", logger="apps.operations.services"):
            transition_property_status(
                property=prop, new_status=PropertyStatus.SOLD, actor=actor
            )
        assert "listing_publication_requires_manual_takedown" not in caplog.text


class TestNoListings:
    def test_transition_without_listings_is_safe(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        transition_property_status(
            property=prop, new_status=PropertyStatus.SOLD, actor=actor
        )
        prop.refresh_from_db()
        assert prop.status == PropertyStatus.SOLD