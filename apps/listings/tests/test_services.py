import pytest
import logging

from decimal import Decimal
from unittest.mock import patch

from django.db import IntegrityError, transaction

from apps.listings.choices import (
    ListingStatus,
    OperationType,
    PublicationChannel,
    PublicationStatus,
)
from apps.listings.exceptions import ListingValidationError, ListingPublicationRequirementsError
from apps.listings.models import Listing, ListingPriceHistory
from apps.listings.services import (
    archive_listing,
    create_listing,
    create_listing_publication,
    update_listing_price,
    update_listing_status,
    update_publication_status,
)
from apps.listings.tests.factories import ListingFactory, ListingPublicationFactory
from apps.properties.tests.factories import PropertyFactory


logger = logging.getLogger(__name__)


class TestCreateListing:
    def test_creates_listing_as_draft(self, db, actor):
        prop = PropertyFactory()
        listing = create_listing(
            property=prop,
            operation_type=OperationType.RENT,
            price=Decimal("50000.00"),
            currency="ARS",
            period="monthly",
            actor=actor,
        )
        assert listing.status == ListingStatus.DRAFT

    def test_creates_initial_price_history_entry(self, db, actor):
        prop = PropertyFactory()
        listing = create_listing(
            property=prop,
            operation_type=OperationType.RENT,
            price=Decimal("50000.00"),
            currency="ARS",
            period="monthly",
            actor=actor,
        )
        assert ListingPriceHistory.objects.filter(listing=listing).count() == 1

    @pytest.mark.parametrize("blocking_status", [
        ListingStatus.DRAFT,
        ListingStatus.PENDING_APPROVAL,
        ListingStatus.PUBLISHED,
        ListingStatus.PAUSED,
    ])
    def test_raises_if_non_closed_listing_exists_for_same_operation(
        self, db, actor, blocking_status
    ):
        existing = ListingFactory(
            operation_type=OperationType.SALE,
            status=blocking_status,
        )
        with pytest.raises(ListingValidationError):
            create_listing(
                property=existing.property,
                operation_type=OperationType.SALE,
                price=Decimal("100000.00"),
                currency="ARS",
                period="total",
                actor=actor,
            )

    def test_error_message_names_the_blocking_status(self, db, actor):
        """El mensaje es contrato con el socio: tiene que decir QUÉ estado
        bloquea (un borrador pide otra acción que algo publicado)."""
        existing = ListingFactory(
            operation_type=OperationType.SALE,
            status=ListingStatus.DRAFT,
        )
        with pytest.raises(ListingValidationError) as excinfo:
            create_listing(
                property=existing.property,
                operation_type=OperationType.SALE,
                price=Decimal("100000.00"),
                currency="ARS",
                period="total",
                actor=actor,
            )
        assert "Borrador" in str(excinfo.value)

    def test_allows_different_operation_types_on_same_property(self, db, actor):
        prop = PropertyFactory()
        ListingFactory(
            property=prop,
            operation_type=OperationType.SALE,
            status=ListingStatus.PUBLISHED,
        )
        listing = create_listing(
            property=prop,
            operation_type=OperationType.RENT,
            price=Decimal("50000.00"),
            currency="ARS",
            period="monthly",
            actor=actor,
        )
        assert listing.pk is not None

    def test_allows_new_listing_when_previous_is_closed(self, db, actor):
        prop = PropertyFactory()
        ListingFactory(
            property=prop,
            operation_type=OperationType.SALE,
            status=ListingStatus.CLOSED,
        )
        listing = create_listing(
            property=prop,
            operation_type=OperationType.SALE,
            price=Decimal("5000000.00"),
            currency="ARS",
            period="total",
            actor=actor,
        )
        assert listing.pk is not None


class TestUpdateListingPrice:
    def test_updates_price(self, db, actor):
        listing = ListingFactory()
        update_listing_price(listing=listing, price=Decimal("60000.00"), actor=actor)
        listing.refresh_from_db()
        assert listing.price == Decimal("60000.00")

    def test_creates_price_history_entry(self, db, actor):
        listing = ListingFactory()
        update_listing_price(listing=listing, price=Decimal("60000.00"), actor=actor)
        assert ListingPriceHistory.objects.filter(listing=listing).count() == 1

    def test_price_history_grows_with_each_update(self, db, actor):
        listing = ListingFactory()
        update_listing_price(listing=listing, price=Decimal("60000.00"), actor=actor)
        update_listing_price(listing=listing, price=Decimal("70000.00"), actor=actor)
        assert ListingPriceHistory.objects.filter(listing=listing).count() == 2


class TestUpdateListingStatus:
    def test_updates_status(self, db, actor):
        listing = ListingFactory(status=ListingStatus.DRAFT, property__publishable=True)
        update_listing_status(listing=listing, status=ListingStatus.PUBLISHED, actor=actor)
        listing.refresh_from_db()
        assert listing.status == ListingStatus.PUBLISHED

    def test_defensive_branch_logs_critical_on_impossible_duplicate(
        self, db, actor, caplog
    ):
        """La rama es inalcanzable por construcción (constraint del paso 1).
        Se fuerza cegando el guard al revés — exists() devuelve True — y se
        assertean sus dos salidas: log CRITICAL para el operador, error
        genérico para el usuario. Si alguien borra la rama 'porque nunca
        pasa', este test lo frena."""
        listing = ListingFactory(status=ListingStatus.DRAFT)
        with patch("apps.listings.services.Listing.objects.filter") as mock_filter:
            (
                mock_filter.return_value
                .exclude.return_value
                .exclude.return_value
                .exists.return_value
            ) = True
            with caplog.at_level(logging.CRITICAL, logger="apps.listings.services"):
                with pytest.raises(ListingValidationError) as excinfo:
                    update_listing_status(
                        listing=listing,
                        status=ListingStatus.PUBLISHED,
                        actor=actor,
                    )
        assert "Invariante de unicidad vulnerado" in caplog.text
        assert "Error interno" in str(excinfo.value)

    def test_allows_activation_when_existing_listing_is_closed(self, db, actor):
        prop = PropertyFactory(publishable=True)
        ListingFactory(
            property=prop,
            operation_type=OperationType.RENT,
            status=ListingStatus.CLOSED,
        )
        new_listing = ListingFactory(
            property=prop,
            operation_type=OperationType.RENT,
            status=ListingStatus.DRAFT,
        )
        update_listing_status(
            listing=new_listing,
            status=ListingStatus.PUBLISHED,
            actor=actor,
        )
        new_listing.refresh_from_db()
        assert new_listing.status == ListingStatus.PUBLISHED

    def test_activating_already_active_listing_does_not_raise(self, db, actor):
        listing = ListingFactory(status=ListingStatus.PUBLISHED, property__publishable=True)
        update_listing_status(
            listing=listing,
            status=ListingStatus.PUBLISHED,
            actor=actor,
        )
        listing.refresh_from_db()
        assert listing.status == ListingStatus.PUBLISHED


class TestArchiveListing:
    def test_archives_listing(self, db, actor):
        listing = ListingFactory()
        archive_listing(listing=listing, actor=actor)
        listing.refresh_from_db()
        assert listing.deleted_at is not None


class TestCreateListingPublication:
    def test_creates_publication_with_pending_status(self, db, actor):
        listing = ListingFactory()
        publication = create_listing_publication(
            listing=listing,
            channel=PublicationChannel.ZONAPROP,
            actor=actor,
        )
        assert publication.status == PublicationStatus.PENDING

    def test_raises_if_publication_already_exists_for_channel(self, db, actor):
        listing = ListingFactory()
        ListingPublicationFactory(listing=listing, channel=PublicationChannel.ZONAPROP)
        with pytest.raises(ListingValidationError):
            create_listing_publication(
                listing=listing,
                channel=PublicationChannel.ZONAPROP,
                actor=actor,
            )

    def test_allows_same_channel_on_different_listings(self, db, actor):
        listing_a = ListingFactory()
        listing_b = ListingFactory()
        ListingPublicationFactory(listing=listing_a, channel=PublicationChannel.ZONAPROP)
        publication = create_listing_publication(
            listing=listing_b,
            channel=PublicationChannel.ZONAPROP,
            actor=actor,
        )
        assert publication.pk is not None


class TestUpdatePublicationStatus:
    def test_updates_status_to_published_sets_published_at(self, db, actor):
        publication = ListingPublicationFactory(status=PublicationStatus.PENDING)
        update_publication_status(
            publication=publication,
            status=PublicationStatus.PUBLISHED,
            actor=actor,
        )
        publication.refresh_from_db()
        assert publication.published_at is not None

    def test_updates_status_to_failed_does_not_set_published_at(self, db, actor):
        publication = ListingPublicationFactory(status=PublicationStatus.PENDING)
        update_publication_status(
            publication=publication,
            status=PublicationStatus.FAILED,
            actor=actor,
        )
        publication.refresh_from_db()
        assert publication.published_at is None

    def test_always_updates_last_synced_at(self, db, actor):
        publication = ListingPublicationFactory(status=PublicationStatus.PENDING)
        assert publication.last_synced_at is None
        update_publication_status(
            publication=publication,
            status=PublicationStatus.FAILED,
            actor=actor,
        )
        publication.refresh_from_db()
        assert publication.last_synced_at is not None

    def test_stores_external_id_when_provided(self, db, actor):
        publication = ListingPublicationFactory(status=PublicationStatus.PENDING)
        update_publication_status(
            publication=publication,
            status=PublicationStatus.PUBLISHED,
            external_id="ZP-12345",
            actor=actor,
        )
        publication.refresh_from_db()
        assert publication.external_id == "ZP-12345"

    def test_stores_metadata_when_provided(self, db, actor):
        publication = ListingPublicationFactory(status=PublicationStatus.PENDING)
        metadata = {"response_code": 200, "url": "https://zonaprop.com/123"}
        update_publication_status(
            publication=publication,
            status=PublicationStatus.PUBLISHED,
            metadata=metadata,
            actor=actor,
        )
        publication.refresh_from_db()
        assert publication.metadata == metadata

    def test_empty_external_id_does_not_overwrite(self, db, actor):
        publication = ListingPublicationFactory(
            status=PublicationStatus.PUBLISHED,
            external_id="ZP-12345",
        )
        update_publication_status(
            publication=publication,
            status=PublicationStatus.UNPUBLISHED,
            external_id="",
            actor=actor,
        )
        publication.refresh_from_db()
        assert publication.external_id == "ZP-12345"


class TestPublicationGate:
    def test_publishes_complete_property(self, db, actor):
        listing = ListingFactory(status=ListingStatus.DRAFT, property__publishable=True)
        update_listing_status(listing=listing, status=ListingStatus.PUBLISHED, actor=actor)
        listing.refresh_from_db()
        assert listing.status == ListingStatus.PUBLISHED

    def test_rejects_blank_description(self, db, actor):
        prop = PropertyFactory(publishable=True, description="   ")
        listing = ListingFactory(property=prop, status=ListingStatus.DRAFT)
        with pytest.raises(ListingPublicationRequirementsError) as exc:
            update_listing_status(listing=listing, status=ListingStatus.PUBLISHED, actor=actor)
        assert exc.value.missing == ["description"]
        listing.refresh_from_db()
        assert listing.status == ListingStatus.DRAFT

    def test_rejects_without_photos(self, db, actor):
        prop = PropertyFactory(
            description=(
                "Casa de tres dormitorios con patio, cochera para dos autos, "
                "living comedor amplio, cocina independiente con office y "
                "lavadero cubierto. Muy buena ubicación, sobre calle asfaltada "
                "y a pocas cuadras de escuelas y comercios."
            )
        )
        listing = ListingFactory(property=prop, status=ListingStatus.DRAFT)
        with pytest.raises(ListingPublicationRequirementsError) as exc:
            update_listing_status(listing=listing, status=ListingStatus.PUBLISHED, actor=actor)
        assert exc.value.missing == ["photos"]

    def test_missing_accumulates_all_requirements(self, db, actor):
        listing = ListingFactory(status=ListingStatus.DRAFT)  # propiedad pelada
        with pytest.raises(ListingPublicationRequirementsError) as exc:
            update_listing_status(listing=listing, status=ListingStatus.PUBLISHED, actor=actor)
        assert exc.value.missing == ["description", "photos"]

    def test_gate_error_is_a_validation_error(self, db, actor):
        listing = ListingFactory(status=ListingStatus.DRAFT)
        with pytest.raises(ListingValidationError):
            update_listing_status(listing=listing, status=ListingStatus.PUBLISHED, actor=actor)


class TestListingUnicityRaceCondition:
    def test_partial_constraint_is_the_real_backstop(self, db):
        """El guard del service es un SELECT previo — no cierra la carrera
        entre dos requests concurrentes. La constraint parcial sí. Este
        test la ejercita directo en DB, bypaseando el service.
        """
        existing = ListingFactory(
            operation_type=OperationType.SALE,
            status=ListingStatus.DRAFT,
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ListingFactory(
                    property=existing.property,
                    operation_type=OperationType.SALE,
                    status=ListingStatus.DRAFT,
                )

    def test_integrity_error_translated_to_business_exception(self, db, actor):
        """Guard cegado (simula la carrera: el otro listing se creó entre
        el chequeo y el save) → la DB rechaza → el usuario recibe el
        error de negocio, no el IntegrityError crudo."""
        existing = ListingFactory(
            operation_type=OperationType.SALE,
            status=ListingStatus.DRAFT,
        )
        with patch("apps.listings.services.Listing.objects.filter") as mock_filter:
            mock_filter.return_value.exclude.return_value.first.return_value = None
            with pytest.raises(ListingValidationError) as excinfo:
                create_listing(
                    property=existing.property,
                    operation_type=OperationType.SALE,
                    price=Decimal("100000.00"),
                    currency="ARS",
                    period="total",
                    actor=actor,
                )
        assert "simultáneas" in str(excinfo.value)