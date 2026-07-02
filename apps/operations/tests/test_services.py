import pytest

from apps.operations.exceptions import InvalidPropertyTransition
from apps.operations.services import (
    remandate_property,
    restore_property,
    transition_property_status,
    withdraw_property,
    settle_won_sale
)
from apps.contacts.tests.factories import ContactFactory
from apps.properties.choices import PropertyStatus
from apps.properties.tests.factories import PropertyFactory
from apps.listings.choices import ListingStatus, OperationType, PublicationStatus
from apps.listings.models import Listing, ListingPublication
from apps.listings.tests.factories import ListingFactory, ListingPublicationFactory


def _status(listing: Listing) -> str:
    listing.refresh_from_db()
    return listing.status


class TestTransitionToSold:
    """
    Reconciliación cruda de SOLD: solo pausa el alquiler. El cierre del listing
    de venta NO vive acá — es efecto de settle_won_sale (deal→listing).
    """

    def test_writes_property_status(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        transition_property_status(
            property=prop, new_status=PropertyStatus.SOLD, actor=actor
        )
        prop.refresh_from_db()
        assert prop.status == PropertyStatus.SOLD

    def test_pauses_rent_listing(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        rent = ListingFactory(
            property=prop,
            operation_type=OperationType.RENT,
            status=ListingStatus.PUBLISHED,
        )
        transition_property_status(
            property=prop, new_status=PropertyStatus.SOLD, actor=actor
        )
        assert _status(rent) == ListingStatus.PAUSED

    def test_already_paused_rent_stays_paused(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        rent = ListingFactory(
            property=prop,
            operation_type=OperationType.RENT,
            status=ListingStatus.PAUSED,
        )
        transition_property_status(
            property=prop, new_status=PropertyStatus.SOLD, actor=actor
        )
        assert _status(rent) == ListingStatus.PAUSED

    def test_does_not_close_sale_listing(self, db, actor):
        # el cierre de venta es efecto de settle_won_sale, no de la transición.
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        sale = ListingFactory(
            property=prop,
            operation_type=OperationType.SALE,
            status=ListingStatus.PUBLISHED,
        )
        transition_property_status(
            property=prop, new_status=PropertyStatus.SOLD, actor=actor
        )
        assert _status(sale) == ListingStatus.PUBLISHED


class TestSettleWonSale:
    def test_available_closes_sale_and_transitions_sold(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        sale = ListingFactory(
            property=prop,
            operation_type=OperationType.SALE,
            status=ListingStatus.PUBLISHED,
        )
        settle_won_sale(property=prop, actor=actor)
        prop.refresh_from_db()
        assert prop.status == PropertyStatus.SOLD
        assert _status(sale) == ListingStatus.CLOSED

    def test_available_with_rent_pauses_rent(self, db, actor):
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
        settle_won_sale(property=prop, actor=actor)
        assert _status(sale) == ListingStatus.CLOSED
        assert _status(rent) == ListingStatus.PAUSED

    def test_rented_closes_sale_keeps_rented(self, db, actor):
        # precedencia: vender una unidad alquilada cierra el listing de venta
        # pero NO pisa la ocupación — sigue RENTED, alquiler intacto.
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
        settle_won_sale(property=prop, actor=actor)
        prop.refresh_from_db()
        assert prop.status == PropertyStatus.RENTED
        assert _status(sale) == ListingStatus.CLOSED
        assert _status(rent) == ListingStatus.PUBLISHED


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
        # un listing CLOSED queda quieto al volver a AVAILABLE. Se prueba desde
        # UNAVAILABLE (restore), un origen que el guard de SOLD permite; el mismo
        # comportamiento sobre el camino SOLD→AVAILABLE lo cubre TestRemandate.
        prop = PropertyFactory(status=PropertyStatus.UNAVAILABLE)
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
        assert listing.status == ListingStatus.PAUSED
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


class TestWithdrawProperty:
    def test_available_to_unavailable_pauses_listings(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        rent = ListingFactory(
            property=prop,
            operation_type=OperationType.RENT,
            status=ListingStatus.PUBLISHED,
        )
        withdraw_property(property=prop, actor=actor)
        prop.refresh_from_db()
        assert prop.status == PropertyStatus.UNAVAILABLE
        assert _status(rent) == ListingStatus.PAUSED

    def test_rejects_non_available(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.RENTED)
        with pytest.raises(InvalidPropertyTransition):
            withdraw_property(property=prop, actor=actor)


class TestRestoreProperty:
    def test_unavailable_to_available_unpauses_listings(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.UNAVAILABLE)
        rent = ListingFactory(
            property=prop,
            operation_type=OperationType.RENT,
            status=ListingStatus.PAUSED,
        )
        restore_property(property=prop, actor=actor)
        prop.refresh_from_db()
        assert prop.status == PropertyStatus.AVAILABLE
        assert _status(rent) == ListingStatus.PUBLISHED

    def test_rejects_non_unavailable(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        with pytest.raises(InvalidPropertyTransition):
            restore_property(property=prop, actor=actor)


class TestRemandateProperty:
    def test_sold_to_available_updates_owner(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.SOLD)
        buyer = ContactFactory()
        remandate_property(
            property=prop, new_owner_contact_id=buyer.pk, actor=actor
        )
        prop.refresh_from_db()
        assert prop.status == PropertyStatus.AVAILABLE
        assert prop.owner_contact_id == buyer.pk

    def test_revives_paused_rent_leaves_closed_sale(self, db, actor):
        # el flujo inversor: el alquiler parkeado revive, la venta concretada
        # queda como historia (no se resucita).
        prop = PropertyFactory(status=PropertyStatus.SOLD)
        buyer = ContactFactory()
        rent = ListingFactory(
            property=prop,
            operation_type=OperationType.RENT,
            status=ListingStatus.PAUSED,
        )
        sale = ListingFactory(
            property=prop,
            operation_type=OperationType.SALE,
            status=ListingStatus.CLOSED,
        )
        remandate_property(
            property=prop, new_owner_contact_id=buyer.pk, actor=actor
        )
        assert _status(rent) == ListingStatus.PUBLISHED
        assert _status(sale) == ListingStatus.CLOSED

    def test_rejects_non_sold(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        buyer = ContactFactory()
        with pytest.raises(InvalidPropertyTransition):
            remandate_property(
                property=prop, new_owner_contact_id=buyer.pk, actor=actor
            )


class TestSoldGuard:
    def test_incidental_transition_out_of_sold_raises(self, db, actor):
        prop = PropertyFactory(status=PropertyStatus.SOLD)
        with pytest.raises(InvalidPropertyTransition):
            transition_property_status(
                property=prop, new_status=PropertyStatus.RENTED, actor=actor
            )

    def test_guard_blocks_even_to_available(self, db, actor):
        # ni siquiera SOLD → AVAILABLE pasa por la función pública: la única
        # salida es remandate_property, que entra por el motor interno.
        prop = PropertyFactory(status=PropertyStatus.SOLD)
        with pytest.raises(InvalidPropertyTransition):
            transition_property_status(
                property=prop, new_status=PropertyStatus.AVAILABLE, actor=actor
            )

    def test_remandate_is_the_sanctioned_exit(self, db, actor):
        # remandate NO es bloqueado por el guard (va por el motor).
        prop = PropertyFactory(status=PropertyStatus.SOLD)
        buyer = ContactFactory()
        remandate_property(
            property=prop, new_owner_contact_id=buyer.pk, actor=actor
        )
        prop.refresh_from_db()
        assert prop.status == PropertyStatus.AVAILABLE