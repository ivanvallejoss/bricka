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

    def test_updates_actor_as_updated_by(self, db, actor):
        other_actor = UserFactory()
        prop = PropertyFactory(created_by=other_actor, updated_by=other_actor)
        update_property(property=prop, city="Buenos Aires", actor=actor)
        prop.refresh_from_db()
        assert prop.updated_by == actor
    
    def test_omitted_fields_are_not_touched(self, db, actor):
        prop = PropertyFactory(title="Depto céntrico", parking_spaces=2)
        update_property(property=prop, city="Corrientes", actor=actor)
        prop.refresh_from_db()
        assert prop.title == "Depto céntrico"
        assert prop.parking_spaces == 2
        assert prop.city == "Corrientes"

    def test_none_blanks_parking_spaces(self, db, actor):
        prop = PropertyFactory(parking_spaces=2)
        update_property(property=prop, parking_spaces=None, actor=actor)
        prop.refresh_from_db()
        assert prop.parking_spaces is None

    def test_zero_parking_spaces_is_a_value(self, db, actor):
        prop = PropertyFactory(parking_spaces=2)
        update_property(property=prop, parking_spaces=0, actor=actor)
        prop.refresh_from_db()
        assert prop.parking_spaces == 0

    def test_empty_string_blanks_description(self, db, actor):
        prop = PropertyFactory(description="Luminoso 3 ambientes")
        update_property(property=prop, description="", actor=actor)
        prop.refresh_from_db()
        assert prop.description == ""

    def test_none_unsets_owner_contact(self, db, actor):
        owner = ContactFactory()
        prop = PropertyFactory(owner_contact=owner)
        update_property(property=prop, owner_contact_id=None, actor=actor)
        prop.refresh_from_db()
        assert prop.owner_contact_id is None


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

    def test_becomes_cover_when_property_has_media_but_no_cover(self, db, actor):
        prop = PropertyFactory()
        PropertyMediaFactory(property=prop, is_cover=False, r2_key="media/huerfana.jpg")
        media = upload_property_media(
            property=prop,
            r2_key="media/properties/test/nueva.jpg",
            mime_type="image/jpeg",
            actor=actor,
        )
        assert media.is_cover is True

    def test_accepts_none_actor_as_system_action(self, db):
        prop = PropertyFactory()
        media = upload_property_media(
            property=prop,
            r2_key="media/properties/test/sistema.jpg",
            mime_type="image/jpeg",
            actor=None,
        )
        assert media.created_by is None


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

    def test_keeps_single_cover_when_target_is_already_cover(self, db):
        prop = PropertyFactory()
        cover = PropertyMediaFactory(property=prop, is_cover=True, r2_key="media/c.jpg")
        PropertyMediaFactory(property=prop, is_cover=False, r2_key="media/o.jpg")
        set_cover_media(media=cover)
        assert PropertyMedia.objects.filter(
            property=prop, is_cover=True
        ).count() == 1


class TestDeletePropertyMedia:
    def test_hard_deletes_record(self, db):
        media = PropertyMediaFactory()
        media_pk = media.pk
        delete_property_media(media=media)
        assert not PropertyMedia.objects.filter(pk=media_pk).exists()

    def test_deleting_cover_leaves_property_without_cover(self, db):
        """
        Pin de comportamiento actual, NO de comportamiento deseado:
        el service no promueve otra foto a cover. Qué hacer con este
        estado es decisión de S2 (deuda registrada en el cierre de S1).
        Si este test rompe, alguien cambió la política — que sea a
        propósito y actualice la deuda.
        """
        prop = PropertyFactory()
        cover = PropertyMediaFactory(property=prop, is_cover=True, r2_key="media/c.jpg")
        PropertyMediaFactory(property=prop, is_cover=False, r2_key="media/o.jpg")
        delete_property_media(media=cover)
        assert not PropertyMedia.objects.filter(
            property=prop, is_cover=True
        ).exists()


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
        with pytest.raises(PropertyValidationError, match="desconocidas"):
            self._create(actor, features=["balcon", "slug_inexistente"])

    def test_create_rejects_inactive_slug(self, db, actor):
        FeatureFactory(slug="feature_retirada_test", is_active=False)
        with pytest.raises(PropertyValidationError, match="inactivas"):
            self._create(actor, features=["feature_retirada_test"])

    def test_rejection_writes_nothing(self, db, actor):
        with pytest.raises(PropertyValidationError):
            self._create(actor, features=["inexistente"])
        assert Property.objects.count() == 0

    def test_update_omitted_features_are_not_touched(self, db, actor):
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