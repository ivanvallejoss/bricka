import uuid

import pytest

from apps.contacts.tests.factories import ContactFactory
from apps.listings.choices import ListingStatus, OperationType
from apps.listings.tests.factories import ListingFactory
from apps.properties.choices import PropertyStatus, PropertyType
from apps.properties.models import Property
from apps.properties.selectors import (
    PropertyFilters,
    get_property_detail,
    get_property_list,
    get_property_media,
    get_property_preview,
)
from apps.properties.tests.factories import PropertyFactory, PropertyMediaFactory


class TestGetPropertyList:
    def test_excludes_archived_properties(self, db, actor):
        PropertyFactory()
        archived = PropertyFactory()
        archived.soft_delete(actor=actor)
        assert get_property_list().count() == 1

    def test_no_filters_returns_all_active(self, db):
        PropertyFactory.create_batch(3)
        assert get_property_list(filters=None).count() == 3

    def test_filter_by_status_list(self, db):
        PropertyFactory(status=PropertyStatus.AVAILABLE)
        PropertyFactory(status=PropertyStatus.RENTED)
        PropertyFactory(status=PropertyStatus.SOLD)
        result = get_property_list(
            filters=PropertyFilters(
                status=[PropertyStatus.AVAILABLE, PropertyStatus.RENTED]
            )
        )
        assert result.count() == 2

    def test_filter_by_operation_type_via_subquery(self, db):
        prop_with_sale = PropertyFactory()
        ListingFactory(
            property=prop_with_sale,
            operation_type=OperationType.SALE,
            status=ListingStatus.PUBLISHED,
        )
        PropertyFactory()  # sin listing activo

        result = get_property_list(
            filters=PropertyFilters(operation_type=OperationType.SALE)
        )
        assert result.count() == 1
        assert result.first().pk == prop_with_sale.pk

    def test_filter_by_property_type(self, db):
        PropertyFactory(property_type=PropertyType.APARTMENT)
        PropertyFactory(property_type=PropertyType.HOUSE)
        result = get_property_list(
            filters=PropertyFilters(property_type=PropertyType.APARTMENT)
        )
        assert result.count() == 1

    def test_filter_by_is_external(self, db):
        PropertyFactory(is_external=False)
        PropertyFactory(is_external=True)
        result = get_property_list(filters=PropertyFilters(is_external=True))
        assert result.count() == 1

    def test_annotates_has_sale_listing(self, db):
        prop = PropertyFactory()
        ListingFactory(
            property=prop,
            operation_type=OperationType.SALE,
            status=ListingStatus.PUBLISHED,
        )
        result = get_property_list().get(pk=prop.pk)
        assert result.has_sale_listing is True

    def test_annotates_has_rent_listing(self, db):
        prop = PropertyFactory()
        ListingFactory(
            property=prop,
            operation_type=OperationType.RENT,
            status=ListingStatus.PUBLISHED,
        )
        result = get_property_list().get(pk=prop.pk)
        assert result.has_rent_listing is True

    def test_annotations_are_independent(self, db):
        prop = PropertyFactory()
        ListingFactory(
            property=prop,
            operation_type=OperationType.SALE,
            status=ListingStatus.PUBLISHED,
        )
        result = get_property_list().get(pk=prop.pk)
        assert result.has_sale_listing is True
        assert result.has_rent_listing is False


class TestGetPropertyPreview:
    def test_returns_property(self, db):
        prop = PropertyFactory()
        result = get_property_preview(prop.pk)
        assert result.pk == prop.pk

    def test_raises_if_not_found(self, db):
        with pytest.raises(Property.DoesNotExist):
            get_property_preview(uuid.uuid4())

    def test_raises_if_archived(self, db, actor):
        prop = PropertyFactory()
        prop.soft_delete(actor=actor)
        with pytest.raises(Property.DoesNotExist):
            get_property_preview(prop.pk)

    def test_prefetches_only_cover_media(self, db):
        prop = PropertyFactory()
        PropertyMediaFactory(property=prop, is_cover=True, r2_key="media/cover.jpg")
        PropertyMediaFactory(property=prop, is_cover=False, r2_key="media/other.jpg")

        result = get_property_preview(prop.pk)
        assert len(result.cover_media_list) == 1
        assert result.cover_media_list[0].is_cover is True


class TestGetPropertyDetail:
    def test_returns_property(self, db):
        prop = PropertyFactory()
        result = get_property_detail(prop.pk)
        assert result.pk == prop.pk

    def test_raises_if_not_found(self, db):
        with pytest.raises(Property.DoesNotExist):
            get_property_detail(uuid.uuid4())

    def test_raises_if_archived(self, db, actor):
        prop = PropertyFactory()
        prop.soft_delete(actor=actor)
        with pytest.raises(Property.DoesNotExist):
            get_property_detail(prop.pk)

    def test_select_related_owner_contact_no_extra_queries(
        self, db, django_assert_num_queries
    ):
        contact = ContactFactory()
        prop = PropertyFactory(owner_contact=contact)

        result = get_property_detail(prop.pk)
        with django_assert_num_queries(0):
            _ = result.owner_contact.full_name


class TestGetPropertyMedia:
    def test_returns_media_for_property(self, db):
        prop = PropertyFactory()
        PropertyMediaFactory(property=prop, r2_key="media/1.jpg")
        PropertyMediaFactory(property=prop, r2_key="media/2.jpg")
        assert get_property_media(prop.pk).count() == 2

    def test_raises_if_property_not_found(self, db):
        with pytest.raises(Property.DoesNotExist):
            get_property_media(uuid.uuid4())

    def test_isolates_media_by_property(self, db):
        prop_a = PropertyFactory()
        prop_b = PropertyFactory()
        PropertyMediaFactory(property=prop_a, r2_key="media/a.jpg")
        PropertyMediaFactory(property=prop_b, r2_key="media/b.jpg")

        result = get_property_media(prop_a.pk)
        assert result.count() == 1
        assert result.first().r2_key == "media/a.jpg"

    def test_returns_empty_queryset_if_no_media(self, db):
        prop = PropertyFactory()
        assert get_property_media(prop.pk).count() == 0