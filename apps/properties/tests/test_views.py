import json
from uuid import uuid4
from unittest.mock import MagicMock

import pytest
from django.urls import reverse

from botocore.exceptions import ClientError

from apps.common import storage

from apps.contacts.tests.factories import ContactFactory

from apps.properties.services import MAX_PHOTOS_PER_PROPERTY
from apps.properties.tests.factories import PropertyFactory, PropertyMediaFactory
from apps.properties.models import PropertyMedia, Feature, Property
from apps.properties.services import MAX_PHOTOS_PER_PROPERTY


@pytest.fixture
def stub_r2(monkeypatch, settings):
    """Borde R2 (S1): se stubea storage._client; ni la firma ni el head_object tocan boto3 real."""
    settings.R2_PUBLIC_MEDIA_BUCKET = "media-test"
    settings.R2_PUBLIC_MEDIA_BASE_URL = "https://cdn.test"
    client = MagicMock()
    client.generate_presigned_url.return_value = "https://signed.test/put"
    monkeypatch.setattr(storage, "_client", lambda: client)
    return client

def _head_error(status):
    return ClientError(
        {"Error": {"Code": str(status)}, "ResponseMetadata": {"HTTPStatusCode": status}},
        "HeadObject",
    )


class TestMediaSign:
    def _url(self, prop):
        return reverse("properties:media_sign", kwargs={"pk": prop.pk})

    def _post(self, client, prop, **payload):
        return client.post(
            self._url(prop),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_signs_valid_upload(self, auth_client, stub_r2, db):
        prop = PropertyFactory()
        resp = self._post(auth_client, prop, content_type="image/jpeg", size=1024)
        assert resp.status_code == 200
        body = resp.json()
        assert body["url"] == "https://signed.test/put"
        assert body["key"].startswith(f"properties/{prop.pk}/")
        assert body["key"].endswith(".jpg")

    def test_derives_extension_from_mime_not_client(self, auth_client, stub_r2, db):
        prop = PropertyFactory()
        resp = self._post(auth_client, prop, content_type="image/webp", size=1024)
        assert resp.json()["key"].endswith(".webp")

    def test_rejects_disallowed_mime(self, auth_client, stub_r2, db):
        prop = PropertyFactory()
        resp = self._post(auth_client, prop, content_type="image/gif", size=1024)
        assert resp.status_code == 400

    def test_rejects_oversize(self, auth_client, stub_r2, db):
        prop = PropertyFactory()
        resp = self._post(auth_client, prop, content_type="image/jpeg", size=11 * 1024 * 1024)
        assert resp.status_code == 400

    def test_rejects_when_ceiling_reached(self, auth_client, stub_r2, db):
        prop = PropertyFactory()
        for i in range(MAX_PHOTOS_PER_PROPERTY):
            PropertyMediaFactory(property=prop, r2_key=f"media/{prop.pk}/{i}.jpg")
        resp = self._post(auth_client, prop, content_type="image/jpeg", size=1024)
        assert resp.status_code == 409

    def test_requires_post(self, auth_client, db):
        prop = PropertyFactory()
        resp = auth_client.get(self._url(prop))
        assert resp.status_code == 405
        

class TestMediaConfirm:
    def _url(self, prop):
        return reverse("properties:media_confirm", kwargs={"pk": prop.pk})

    def _key(self, prop, ext=".jpg"):
        return f"properties/{prop.pk}/{uuid4()}{ext}"

    def _post(self, client, prop, key):
        return client.post(
            self._url(prop),
            data=json.dumps({"key": key}),
            content_type="application/json",
        )

    def test_confirms_and_registers_media(self, auth_client, stub_r2, db):
        stub_r2.head_object.return_value = {}
        prop = PropertyFactory()
        key = self._key(prop)
        resp = self._post(auth_client, prop, key)
        assert resp.status_code == 200
        assert PropertyMedia.objects.filter(property=prop, r2_key=key).exists()
        assert b"data-media-id" in resp.content
        assert b'hx-swap-oob="true"' in resp.content

    def test_first_media_is_cover_in_response(self, auth_client, stub_r2, db):
        stub_r2.head_object.return_value = {}
        prop = PropertyFactory()
        resp = self._post(auth_client, prop, self._key(prop))
        assert b"Portada" in resp.content

    def test_rejects_when_object_missing_in_r2(self, auth_client, stub_r2, db):
        stub_r2.head_object.side_effect = _head_error(404)
        prop = PropertyFactory()
        resp = self._post(auth_client, prop, self._key(prop))
        assert resp.status_code == 422
        assert not PropertyMedia.objects.filter(property=prop).exists()

    def test_idempotent_on_duplicate_key(self, auth_client, stub_r2, db):
        stub_r2.head_object.return_value = {}
        prop = PropertyFactory()
        key = self._key(prop)
        self._post(auth_client, prop, key)
        resp = self._post(auth_client, prop, key)
        assert resp.status_code == 200
        assert PropertyMedia.objects.filter(property=prop, r2_key=key).count() == 1

    def test_rejects_key_from_other_property(self, auth_client, stub_r2, db):
        stub_r2.head_object.return_value = {}
        prop = PropertyFactory()
        other = PropertyFactory()
        foreign_key = f"properties/{other.pk}/{uuid4()}.jpg"
        resp = self._post(auth_client, prop, foreign_key)
        assert resp.status_code == 400
        assert not PropertyMedia.objects.filter(r2_key=foreign_key).exists()

    def test_rejects_key_with_disallowed_extension(self, auth_client, stub_r2, db):
        stub_r2.head_object.return_value = {}
        prop = PropertyFactory()
        resp = self._post(auth_client, prop, self._key(prop, ext=".gif"))
        assert resp.status_code == 400

    def test_rejects_when_ceiling_reached(self, auth_client, stub_r2, db):
        stub_r2.head_object.return_value = {}
        prop = PropertyFactory()
        for i in range(MAX_PHOTOS_PER_PROPERTY):
            PropertyMediaFactory(property=prop, r2_key=f"properties/{prop.pk}/{i}.jpg")
        resp = self._post(auth_client, prop, self._key(prop))
        assert resp.status_code == 409


class TestMediaSetCover:
    def _url(self, media):
        return reverse("properties:media_set_cover", kwargs={"id": media.id})

    def test_sets_cover_and_renders_gallery(self, auth_client, stub_r2, db):
        prop = PropertyFactory()
        first = PropertyMediaFactory(property=prop, is_cover=True, order=0, r2_key=f"properties/{prop.pk}/a.jpg")
        second = PropertyMediaFactory(property=prop, is_cover=False, order=1, r2_key=f"properties/{prop.pk}/b.jpg")
        resp = auth_client.post(self._url(second))
        assert resp.status_code == 200
        first.refresh_from_db()
        second.refresh_from_db()
        assert second.is_cover is True
        assert first.is_cover is False
        assert b'id="media-gallery"' in resp.content

    def test_requires_post(self, auth_client, db):
        media = PropertyMediaFactory(r2_key="properties/x/a.jpg")
        resp = auth_client.get(self._url(media))
        assert resp.status_code == 405


class TestMediaDelete:
    def _url(self, media):
        return reverse("properties:media_delete", kwargs={"id": media.id})

    def test_deletes_r2_then_db_and_renders_gallery(self, auth_client, stub_r2, db):
        prop = PropertyFactory()
        media = PropertyMediaFactory(property=prop, is_cover=False, order=1, r2_key=f"properties/{prop.pk}/a.jpg")
        PropertyMediaFactory(property=prop, is_cover=True, order=0, r2_key=f"properties/{prop.pk}/cover.jpg")
        resp = auth_client.post(self._url(media))
        assert resp.status_code == 200
        stub_r2.delete_object.assert_called_once()
        assert not PropertyMedia.objects.filter(pk=media.pk).exists()
        assert b'id="media-gallery"' in resp.content

    def test_deleting_cover_promotes_and_renders_new_cover(self, auth_client, stub_r2, db):
        prop = PropertyFactory()
        cover = PropertyMediaFactory(property=prop, is_cover=True, order=0, r2_key=f"properties/{prop.pk}/a.jpg")
        heir = PropertyMediaFactory(property=prop, is_cover=False, order=1, r2_key=f"properties/{prop.pk}/b.jpg")
        resp = auth_client.post(self._url(cover))
        assert resp.status_code == 200
        heir.refresh_from_db()
        assert heir.is_cover is True
        assert b"Portada" in resp.content

    def test_requires_post(self, auth_client, db):
        media = PropertyMediaFactory(r2_key="properties/x/a.jpg")
        resp = auth_client.get(self._url(media))
        assert resp.status_code == 405


class TestMediaReorder:
    def _url(self, prop):
        return reverse("properties:media_reorder", kwargs={"pk": prop.pk})

    def _post(self, client, prop, ids):
        return client.post(
            self._url(prop),
            data=json.dumps({"ordered_ids": ids}),
            content_type="application/json",
        )

    def test_reorders_returns_204(self, auth_client, db):
        prop = PropertyFactory()
        a = PropertyMediaFactory(property=prop, order=0, r2_key=f"properties/{prop.pk}/a.jpg")
        b = PropertyMediaFactory(property=prop, order=1, r2_key=f"properties/{prop.pk}/b.jpg")
        resp = self._post(auth_client, prop, [str(b.id), str(a.id)])
        assert resp.status_code == 204
        a.refresh_from_db()
        b.refresh_from_db()
        assert (b.order, a.order) == (0, 1)

    def test_stale_set_resyncs_gallery_without_writing(self, auth_client, stub_r2, db):
        prop = PropertyFactory()
        a = PropertyMediaFactory(property=prop, order=0, r2_key=f"properties/{prop.pk}/a.jpg")
        b = PropertyMediaFactory(property=prop, order=1, r2_key=f"properties/{prop.pk}/b.jpg")
        resp = self._post(auth_client, prop, [str(a.id)])  # falta b (borrado concurrente)
        assert resp.status_code == 200
        assert b'id="media-gallery"' in resp.content
        a.refresh_from_db()
        b.refresh_from_db()
        assert (a.order, b.order) == (0, 1)

    def test_malformed_body_returns_400(self, auth_client, db):
        prop = PropertyFactory()
        resp = self._post(auth_client, prop, "not-a-list")
        assert resp.status_code == 400

    def test_requires_post(self, auth_client, db):
        prop = PropertyFactory()
        resp = auth_client.get(self._url(prop))
        assert resp.status_code == 405


class TestPropertyEdit:
    def test_renders_edit_page_with_gallery_and_uploader(self, auth_client, stub_r2, db):
        prop = PropertyFactory()
        PropertyMediaFactory(property=prop, r2_key=f"properties/{prop.pk}/a.jpg")
        resp = auth_client.get(reverse("properties:edit", kwargs={"pk": prop.pk}))
        assert resp.status_code == 200
        assert b'id="media-gallery"' in resp.content
        assert b'id="media-grid"' in resp.content
        assert b"mediaUploader(" in resp.content

    def test_404_on_missing_property(self, auth_client, db):
        resp = auth_client.get(reverse("properties:edit", kwargs={"pk": uuid4()}))
        assert resp.status_code == 404

    def _valid_edit_data(self, **overrides):
        data = {
            "title": "Nuevo título", "description": "Una descripción.",
            "address_line": "Calle 1", "city": "Resistencia", "province": "Chaco",
            "neighborhood": "Centro", "area_m2": "80", "bedrooms": "3",
            "bathrooms": "2", "parking_spaces": "1", "year_built": "2010",
            "youtube_video_url": "",
            "owner_contact_id": "",
        }
        data.update(overrides)
        return data

    def test_edit_post_saves_scalar_fields(self, auth_client, stub_r2, db):
        prop = PropertyFactory(title="Viejo", city="Corrientes")
        resp = auth_client.post(
            reverse("properties:edit", kwargs={"pk": prop.pk}),
            data=self._valid_edit_data(),
        )
        assert resp.status_code == 302
        prop.refresh_from_db()
        assert prop.title == "Nuevo título"
        assert prop.city == "Resistencia"
        assert prop.bedrooms == 3

    def test_edit_post_invalid_rerenders_with_errors(self, auth_client, stub_r2, db):
        prop = PropertyFactory()
        resp = auth_client.post(
            reverse("properties:edit", kwargs={"pk": prop.pk}),
            data=self._valid_edit_data(address_line="", city="", province=""),
        )
        assert resp.status_code == 200
        assert b"border-danger-text" in resp.content

    def test_edit_post_replaces_features(self, auth_client, stub_r2, db):
        prop = PropertyFactory()
        feats = list(Feature.objects.filter(is_active=True)[:2])
        assert len(feats) >= 2
        old, new = feats[0], feats[1]
        prop.features.add(old)
        resp = auth_client.post(
            reverse("properties:edit", kwargs={"pk": prop.pk}),
            data=self._valid_edit_data(features=[new.slug]),
        )
        assert resp.status_code == 302
        prop.refresh_from_db()
        assert set(prop.features.values_list("slug", flat=True)) == {new.slug}

    def test_edit_post_empty_features_clears(self, auth_client, stub_r2, db):
        prop = PropertyFactory()
        feat = Feature.objects.filter(is_active=True).first()
        prop.features.add(feat)
        resp = auth_client.post(
            reverse("properties:edit", kwargs={"pk": prop.pk}),
            data=self._valid_edit_data(),  # sin features → vacía
        )
        assert resp.status_code == 302
        prop.refresh_from_db()
        assert prop.features.count() == 0

    def test_edit_post_invalid_preserves_checked_features(self, auth_client, stub_r2, db):
        prop = PropertyFactory()
        feat = Feature.objects.filter(is_active=True).first()
        resp = auth_client.post(
            reverse("properties:edit", kwargs={"pk": prop.pk}),
            data=self._valid_edit_data(address_line="", features=[feat.slug]),
        )
        assert resp.status_code == 200
        assert feat.slug in resp.context["selected_slugs"]

    def test_edit_post_sets_owner(self, auth_client, stub_r2, db):
        prop = PropertyFactory()
        contact = ContactFactory()
        resp = auth_client.post(
            reverse("properties:edit", kwargs={"pk": prop.pk}),
            data=self._valid_edit_data(owner_contact_id=str(contact.pk)),
        )
        assert resp.status_code == 302
        prop.refresh_from_db()
        assert prop.owner_contact == contact


class TestPropertyNew:
    def _create_data(self, **overrides):
        base = {
            "property_type": "apartment", "address_line": "Calle 1",
            "city": "Resistencia", "province": "Chaco", "neighborhood": "",
            "is_external": "", "agency_name": "",
        }
        base.update(overrides)
        return base

    def test_get_renders_form(self, auth_client, db):
        resp = auth_client.get(reverse("properties:new"))
        assert resp.status_code == 200
        assert b'name="property_type"' in resp.content

    def test_post_creates_and_redirects(self, auth_client, db):
        resp = auth_client.post(reverse("properties:new"), data=self._create_data())
        assert resp.status_code == 302
        prop = Property.objects.get()
        assert prop.property_type == "apartment"
        assert prop.city == "Resistencia"

    def test_post_sets_actor(self, auth_client, actor, db):
        auth_client.post(reverse("properties:new"), data=self._create_data())
        prop = Property.objects.get()
        assert prop.created_by == actor  # el audit trail nace acá

    def test_external_without_agency_shows_nonfield_error(self, auth_client, db):
        resp = auth_client.post(
            reverse("properties:new"),
            data=self._create_data(is_external="on", agency_name=""),
        )
        assert resp.status_code == 200
        assert Property.objects.count() == 0
        assert resp.context["form"].non_field_errors

    def test_external_with_agency_creates(self, auth_client, db):
        resp = auth_client.post(
            reverse("properties:new"),
            data=self._create_data(is_external="on", agency_name="Inmobiliaria X"),
        )
        assert resp.status_code == 302
        assert Property.objects.get().is_external is True