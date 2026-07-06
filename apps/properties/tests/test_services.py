import datetime
from decimal import Decimal

import pytest
from django.db import connection
from django.utils import timezone

from apps.contacts.tests.factories import ContactFactory, UserFactory
from apps.properties.choices import PropertyStatus, PropertyType
from apps.properties.exceptions import PropertyValidationError
from apps.properties.models import ExternalPropertySource, Property, PropertyMedia
from apps.properties.services import (
    archive_property,
    create_property,
    delete_property_media,
    set_cover_media,
    update_property,
    upload_property_media,
)
from .factories import PropertyFactory, PropertyMediaFactory, FeatureFactory


class TestCreateProperty:
    def test_creates_property_with_required_fields(self, db, actor):
        prop = create_property(
            property_type=PropertyType.APARTMENT,
            address_line="Calle 123",
            city="Resistencia",
            province="Chaco",
            area_m2=Decimal("80.00"),
            actor=actor,
        )
        assert prop.pk is not None
        assert prop.deleted_at is None

    def test_assigns_actor_as_created_by(self, db, actor):
        prop = create_property(
            property_type=PropertyType.APARTMENT,
            address_line="Calle 123",
            city="Resistencia",
            province="Chaco",
            area_m2=Decimal("80.00"),
            actor=actor,
        )
        assert prop.created_by == actor
        assert prop.updated_by == actor

    def test_creates_external_property_with_source(self, db, actor):
        prop = create_property(
            property_type=PropertyType.APARTMENT,
            address_line="Calle 123",
            city="Resistencia",
            province="Chaco",
            area_m2=Decimal("80.00"),
            is_external=True,
            agency_name="Agencia Test",
            actor=actor,
        )
        assert prop.is_external is True
        assert ExternalPropertySource.objects.filter(property=prop).exists()

    def test_external_property_source_has_correct_data(self, db, actor):
        prop = create_property(
            property_type=PropertyType.APARTMENT,
            address_line="Calle 123",
            city="Resistencia",
            province="Chaco",
            area_m2=Decimal("80.00"),
            is_external=True,
            agency_name="Agencia Test",
            source_url="https://agencia.com",
            agreed_commission_percent=Decimal("3.00"),
            actor=actor,
        )
        source = ExternalPropertySource.objects.get(property=prop)
        assert source.agency_name == "Agencia Test"
        assert source.source_url == "https://agencia.com"
        assert source.agreed_commission_percent == Decimal("3.00")

    def test_raises_without_agency_name_when_external(self, db, actor):
        with pytest.raises(PropertyValidationError):
            create_property(
                property_type=PropertyType.APARTMENT,
                address_line="Calle 123",
                city="Resistencia",
                province="Chaco",
                area_m2=Decimal("80.00"),
                is_external=True,
                agency_name="",
                actor=actor,
            )

    def test_non_external_skips_source_creation(self, db, actor):
        prop = create_property(
            property_type=PropertyType.APARTMENT,
            address_line="Calle 123",
            city="Resistencia",
            province="Chaco",
            area_m2=Decimal("80.00"),
            actor=actor,
        )
        assert not ExternalPropertySource.objects.filter(property=prop).exists()


class TestUpdateProperty:
    def test_updates_provided_fields(self, db, actor):
        prop = PropertyFactory()
        update_property(
            property=prop,
            city="Buenos Aires",
            area_m2=Decimal("100.00"),
            actor=actor,
        )
        prop.refresh_from_db()
        assert prop.city == "Buenos Aires"
        assert prop.area_m2 == Decimal("100.00")

    def test_updated_at_changes(self, db, actor):
        prop = PropertyFactory()
        old_time = timezone.now() - datetime.timedelta(hours=1)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE properties_property SET updated_at = %s WHERE id = %s",
                [old_time, str(prop.pk)],
            )
        update_property(property=prop, city="Buenos Aires", actor=actor)
        prop.refresh_from_db()
        assert prop.updated_at > old_time

    def test_none_fields_not_modified(self, db, actor):
        prop = PropertyFactory(city="Resistencia")
        update_property(property=prop, city=None, actor=actor)
        prop.refresh_from_db()
        assert prop.city == "Resistencia"

    def test_updates_actor_as_updated_by(self, db, actor):
        other_actor = UserFactory()
        prop = PropertyFactory(created_by=other_actor, updated_by=other_actor)
        update_property(property=prop, city="Buenos Aires", actor=actor)
        prop.refresh_from_db()
        assert prop.updated_by == actor


class TestArchiveProperty:
    def test_archives_property(self, db, actor):
        prop = PropertyFactory()
        archive_property(property=prop, actor=actor)
        prop.refresh_from_db()
        assert prop.deleted_at is not None

    def test_archived_property_excluded_from_default_manager(self, db, actor):
        prop = PropertyFactory()
        archive_property(property=prop, actor=actor)
        assert not Property.objects.filter(pk=prop.pk).exists()


class TestUploadPropertyMedia:
    def test_first_upload_becomes_cover(self, db, actor):
        prop = PropertyFactory()
        media = upload_property_media(
            property=prop,
            r2_key="media/properties/test/foto.jpg",
            mime_type="image/jpeg",
            actor=actor,
        )
        assert media.is_cover is True

    def test_second_upload_is_not_cover(self, db, actor):
        prop = PropertyFactory()
        upload_property_media(
            property=prop,
            r2_key="media/properties/test/foto1.jpg",
            mime_type="image/jpeg",
            actor=actor,
        )
        second = upload_property_media(
            property=prop,
            r2_key="media/properties/test/foto2.jpg",
            mime_type="image/jpeg",
            actor=actor,
        )
        assert second.is_cover is False

    def test_assigns_creator(self, db, actor):
        prop = PropertyFactory()
        media = upload_property_media(
            property=prop,
            r2_key="media/properties/test/foto.jpg",
            mime_type="image/jpeg",
            actor=actor,
        )
        assert media.created_by == actor

    def test_r2_key_persists_correctly(self, db, actor):
        prop = PropertyFactory()
        r2_key = "media/properties/test/foto-especial.jpg"
        media = upload_property_media(
            property=prop,
            r2_key=r2_key,
            mime_type="image/jpeg",
            actor=actor,
        )
        assert media.r2_key == r2_key


class TestSetCoverMedia:
    def test_sets_cover_on_target(self, db):
        media = PropertyMediaFactory(is_cover=False)
        set_cover_media(media=media)
        media.refresh_from_db()
        assert media.is_cover is True

    def test_removes_cover_from_previous(self, db):
        prop = PropertyFactory()
        previous_cover = PropertyMediaFactory(
            property=prop,
            is_cover=True,
            r2_key="media/1.jpg",
        )
        new_media = PropertyMediaFactory(
            property=prop,
            is_cover=False,
            r2_key="media/2.jpg",
        )
        set_cover_media(media=new_media)
        previous_cover.refresh_from_db()
        assert previous_cover.is_cover is False

    def test_does_not_affect_other_properties(self, db):
        prop_a = PropertyFactory()
        prop_b = PropertyFactory()
        cover_b = PropertyMediaFactory(
            property=prop_b,
            is_cover=True,
            r2_key="media/b.jpg",
        )
        media_a = PropertyMediaFactory(
            property=prop_a,
            is_cover=False,
            r2_key="media/a.jpg",
        )
        set_cover_media(media=media_a)
        cover_b.refresh_from_db()
        assert cover_b.is_cover is True


class TestDeletePropertyMedia:
    def test_hard_deletes_record(self, db):
        media = PropertyMediaFactory()
        media_pk = media.pk
        delete_property_media(media=media)
        assert not PropertyMedia.objects.filter(pk=media_pk).exists()


class TestPropertyFeatures:
    def _create(self, actor, **kwargs):
        return create_property(
            property_type=PropertyType.APARTMENT,
            address_line="Calle 123",
            city="Resistencia",
            province="Chaco",
            area_m2=Decimal("80.00"),
            actor=actor,
            **kwargs,
        )

    def test_create_assigns_features_by_slug(self, db, actor):
        FeatureFactory(slug="balcon")
        FeatureFactory(slug="patio")
        prop = self._create(actor, features=["balcon", "patio"])
        assert set(prop.features.values_list("slug", flat=True)) == {"balcon", "patio"}

    def test_create_without_features_leaves_empty(self, db, actor):
        prop = self._create(actor)
        assert prop.features.count() == 0

    def test_create_rejects_unknown_slug(self, db, actor):
        FeatureFactory(slug="balcon")
        with pytest.raises(PropertyValidationError, match="desconocidas"):
            self._create(actor, features=["balcon", "pileta"])

    def test_create_rejects_inactive_slug(self, db, actor):
        FeatureFactory(slug="balcon", is_active=False)
        with pytest.raises(PropertyValidationError, match="inactivas"):
            self._create(actor, features=["balcon"])

    def test_rejection_writes_nothing(self, db, actor):
        with pytest.raises(PropertyValidationError):
            self._create(actor, features=["inexistente"])
        assert Property.objects.count() == 0

    def test_update_none_does_not_touch_features(self, db, actor):
        FeatureFactory(slug="balcon")
        prop = self._create(actor, features=["balcon"])
        update_property(property=prop, city="Corrientes", actor=actor)
        assert list(prop.features.values_list("slug", flat=True)) == ["balcon"]

    def test_update_empty_list_clears_features(self, db, actor):
        FeatureFactory(slug="balcon")
        prop = self._create(actor, features=["balcon"])
        update_property(property=prop, features=[], actor=actor)
        assert prop.features.count() == 0

    def test_update_list_replaces_features(self, db, actor):
        FeatureFactory(slug="balcon")
        FeatureFactory(slug="patio")
        prop = self._create(actor, features=["balcon"])
        update_property(property=prop, features=["patio"], actor=actor)
        assert list(prop.features.values_list("slug", flat=True)) == ["patio"]

    def test_inactive_historical_assignment_survives_unrelated_update(self, db, actor):
        feature = FeatureFactory(slug="balcon")
        prop = self._create(actor, features=["balcon"])
        feature.is_active = False
        feature.save(update_fields=["is_active"])
        update_property(property=prop, city="Corrientes", actor=actor)
        assert list(prop.features.values_list("slug", flat=True)) == ["balcon"]