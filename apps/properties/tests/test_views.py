import json
import pytest
import httpx

from uuid import uuid4
from unittest.mock import MagicMock, patch
from decimal import Decimal

from django.urls import reverse
from django.core.cache import cache
from django.contrib import messages as django_messages
from django.contrib.gis.geos import Point

from botocore.exceptions import ClientError

from apps.common import storage

from apps.contacts.tests.factories import ContactFactory

from apps.listings.tests.factories import ListingFactory
from apps.listings.models import Listing, ListingPriceHistory
from apps.listings.choices import ListingStatus, OperationType, PricePeriod
from apps.listings.exceptions import ListingValidationError

from apps.properties.services import MAX_PHOTOS_PER_PROPERTY
from apps.properties.choices import PropertyStatus
from apps.properties.tests.factories import PropertyFactory, PropertyMediaFactory, ExternalPropertySourceFactory
from apps.properties.models import PropertyMedia, Feature, Property
from apps.properties.services import MAX_PHOTOS_PER_PROPERTY
from apps.properties.views import _operacion_section_context, _location_section_context
from apps.properties.checklist import FLOW_EDIT


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


class TestPropertyNewDetalle:
    def _detalle_data(self, **overrides):
        base = {
            "title": "Nuevo título", "description": "Una descripción.",
            "address_line": "Calle 1", "city": "Resistencia", "province": "Chaco",
            "neighborhood": "", "area_m2": "", "bedrooms": "", "bathrooms": "",
            "parking_spaces": "", "year_built": "", "youtube_video_url": "",
            "owner_contact_id": "",
        }
        base.update(overrides)
        return base

    def test_get_renders_prefilled(self, auth_client, db):
        prop = PropertyFactory(title="Existente")
        resp = auth_client.get(reverse("properties:new_detalle", kwargs={"pk": prop.pk}))
        assert resp.status_code == 200
        assert b'name="title"' in resp.content
        assert b"Existente" in resp.content

    def test_post_saves_and_redirects(self, auth_client, db):
        prop = PropertyFactory(title="Viejo")
        resp = auth_client.post(
            reverse("properties:new_detalle", kwargs={"pk": prop.pk}),
            data=self._detalle_data(),
        )
        assert resp.status_code == 302
        prop.refresh_from_db()
        assert prop.title == "Nuevo título"
    
    def test_post_next_redirects_to_fotos(self, auth_client, db):
        prop = PropertyFactory()
        resp = auth_client.post(
            reverse("properties:new_detalle", kwargs={"pk": prop.pk}),
            data=self._detalle_data(action="next"),
        )
        assert resp.status_code == 302
        assert resp.url == reverse("properties:new_fotos", kwargs={"pk": prop.pk})


class TestPropertyNewFotos:
    def test_renders_fotos_page(self, auth_client, stub_r2, db):
        prop = PropertyFactory()
        resp = auth_client.get(reverse("properties:new_fotos", kwargs={"pk": prop.pk}))
        assert resp.status_code == 200
        assert b'id="media-gallery"' in resp.content
        assert b"mediaUploader(" in resp.content


class TestListingCreate:
    def _url(self, prop):
        return reverse("properties:listing_create", args=[prop.pk])

    def test_creates_draft_listing(self, auth_client, db):
        prop = PropertyFactory()
        resp = auth_client.post(self._url(prop), {
            "operation_type": OperationType.SALE, "price": "120000", "currency": "USD",
        })
        assert resp.status_code == 200
        listing = Listing.objects.get(property=prop)
        assert listing.status == ListingStatus.DRAFT
        assert listing.operation_type == OperationType.SALE

    def test_sale_derives_total_period(self, auth_client, db):
        prop = PropertyFactory()
        auth_client.post(self._url(prop), {
            "operation_type": OperationType.SALE, "price": "120000", "currency": "USD",
        })
        assert Listing.objects.get(property=prop).period == PricePeriod.TOTAL

    def test_rent_derives_monthly_period(self, auth_client, db):
        prop = PropertyFactory()
        auth_client.post(self._url(prop), {
            "operation_type": OperationType.RENT, "price": "50000", "currency": "ARS",
        })
        assert Listing.objects.get(property=prop).period == PricePeriod.MONTHLY

    def test_price_min_acceptable_optional(self, auth_client, db):
        prop = PropertyFactory()
        auth_client.post(self._url(prop), {
            "operation_type": OperationType.SALE, "price": "120000", "currency": "USD",
        })
        assert Listing.objects.get(property=prop).price_min_acceptable is None

    def test_price_min_acceptable_persists(self, auth_client, db):
        prop = PropertyFactory()
        auth_client.post(self._url(prop), {
            "operation_type": OperationType.SALE, "price": "120000",
            "currency": "USD", "price_min_acceptable": "110000",
        })
        assert Listing.objects.get(property=prop).price_min_acceptable == Decimal("110000")

    def test_invalid_operation_type_creates_nothing(self, auth_client, db):
        prop = PropertyFactory()
        resp = auth_client.post(self._url(prop), {
            "operation_type": OperationType.TEMPORARY_RENT, "price": "50000", "currency": "ARS",
        })
        assert resp.status_code == 200
        assert not Listing.objects.filter(property=prop).exists()

    def test_missing_price_creates_nothing(self, auth_client, db):
        prop = PropertyFactory()
        resp = auth_client.post(self._url(prop), {
            "operation_type": OperationType.SALE, "currency": "USD",
        })
        assert resp.status_code == 200
        assert not Listing.objects.filter(property=prop).exists()

    def test_unicidad_race_creates_nothing(self, auth_client, db):
        prop = PropertyFactory()
        ListingFactory(property=prop, operation_type=OperationType.SALE,
                       status=ListingStatus.PUBLISHED)
        resp = auth_client.post(self._url(prop), {
            "operation_type": OperationType.SALE, "price": "120000", "currency": "USD",
        })
        assert resp.status_code == 200
        assert Listing.objects.filter(
            property=prop, operation_type=OperationType.SALE
        ).count() == 1

    def test_get_not_allowed(self, auth_client, db):
        prop = PropertyFactory()
        assert auth_client.get(self._url(prop)).status_code == 405


class TestListingPublish:
    def _url(self, prop, listing):
        return reverse("properties:listing_publish", args=[prop.pk, listing.id])

    def test_publish_success_returns_row(self, auth_client, db):
        prop = PropertyFactory(publishable=True)
        listing = ListingFactory(property=prop, operation_type=OperationType.SALE,
                                 status=ListingStatus.DRAFT)
        resp = auth_client.post(self._url(prop, listing), {"flow": "edit"})
        assert resp.status_code == 200
        assert resp.get("HX-Retarget") is None
        listing.refresh_from_db()
        assert listing.status == ListingStatus.PUBLISHED

    def test_publish_gate_reject_returns_checklist_modal(self, auth_client, db):
        prop = PropertyFactory()  # sin fotos ni descripción → gate falla
        listing = ListingFactory(property=prop, operation_type=OperationType.SALE,
                                 status=ListingStatus.DRAFT)
        resp = auth_client.post(self._url(prop, listing), {"flow": "edit"})
        assert resp.status_code == 200
        assert resp.get("HX-Retarget") == "#modal-container"
        assert "No se puede publicar" in resp.content.decode()
        listing.refresh_from_db()
        assert listing.status == ListingStatus.DRAFT

    def test_publish_validation_error_returns_modal_error(self, auth_client, db):
        """El branching de la view: ListingValidationError → modal_error.
        El escenario de unicidad real es inalcanzable desde la extensión
        de la constraint (la rama del service es defensiva); se inyecta
        el error en la frontera para testear SOLO el ruteo de la view."""
        
        prop = PropertyFactory()
        listing = ListingFactory(property=prop, operation_type=OperationType.SALE,
                status=ListingStatus.PUBLISHED)
        
        with patch(
            "apps.properties.views.update_listing_status",
            side_effect=ListingValidationError("boom"),
        ):
            resp = auth_client.post(self._url(prop, listing), {"flow": "edit"})
            assert resp.status_code == 200
            assert resp.get("HX-Retarget") == "#modal-container"
            assert "boom" in resp.content.decode()

        listing.refresh_from_db()
        assert listing.status == ListingStatus.PUBLISHED

    def test_publish_wrong_property_404(self, auth_client, db):
        prop_a = PropertyFactory()
        prop_b = PropertyFactory()
        listing = ListingFactory(property=prop_a, status=ListingStatus.DRAFT)
        resp = auth_client.post(
            reverse("properties:listing_publish", args=[prop_b.pk, listing.id]),
            {"flow": "edit"},
        )
        assert resp.status_code == 404

    def test_publish_get_not_allowed(self, auth_client, db):
        prop = PropertyFactory()
        listing = ListingFactory(property=prop, status=ListingStatus.DRAFT)
        assert auth_client.get(self._url(prop, listing)).status_code == 405

    def test_publish_gate_reject_wizard_flow_links_to_phases(self, auth_client, db):
        prop = PropertyFactory(description="Corto")  # sin fotos ni descripción → gate falla
        listing = ListingFactory(property=prop, operation_type=OperationType.SALE,
                                 status=ListingStatus.DRAFT)
        resp = auth_client.post(self._url(prop, listing), {"flow": "wizard"})
        assert resp.status_code == 200
        assert resp.get("HX-Retarget") == "#modal-container"
        content = resp.content.decode()
        assert reverse("properties:new_fotos", args=[prop.pk]) in content
        assert reverse("properties:new_detalle", args=[prop.pk]) in content


class TestListingPrice:
    def _url(self, prop, listing):
        return reverse("properties:listing_price", args=[prop.pk, listing.id])

    def test_price_update_success_writes_history(self, auth_client, db):
        prop = PropertyFactory()
        listing = ListingFactory(property=prop, price=Decimal("50000.00"))
        resp = auth_client.post(self._url(prop, listing), {"price": "60000"})
        assert resp.status_code == 200
        listing.refresh_from_db()
        assert listing.price == Decimal("60000.00")
        assert ListingPriceHistory.objects.filter(
            listing=listing, price=Decimal("60000.00")
        ).exists()

    def test_price_update_invalid_keeps_price(self, auth_client, db):
        prop = PropertyFactory()
        listing = ListingFactory(property=prop, price=Decimal("50000.00"))
        resp = auth_client.post(self._url(prop, listing), {"price": "-5"})
        assert resp.status_code == 200
        listing.refresh_from_db()
        assert listing.price == Decimal("50000.00")

    def test_price_get_not_allowed(self, auth_client, db):
        prop = PropertyFactory()
        listing = ListingFactory(property=prop)
        assert auth_client.get(self._url(prop, listing)).status_code == 405


class TestOperacionAvailability:
    def test_both_available_when_no_listings(self, db):
        prop = PropertyFactory()
        ctx = _operacion_section_context(prop, FLOW_EDIT)
        assert [v for v, _ in ctx["available_operations"]] == ["sale", "rent"]

    def test_draft_sale_removes_sale(self, db):
        prop = PropertyFactory()
        ListingFactory(property=prop, operation_type=OperationType.SALE,
                       status=ListingStatus.DRAFT)
        ctx = _operacion_section_context(prop, FLOW_EDIT)
        assert [v for v, _ in ctx["available_operations"]] == ["rent"]

    def test_published_sale_removes_sale(self, db):
        prop = PropertyFactory()
        ListingFactory(property=prop, operation_type=OperationType.SALE,
                       status=ListingStatus.PUBLISHED)
        ctx = _operacion_section_context(prop, FLOW_EDIT)
        assert [v for v, _ in ctx["available_operations"]] == ["rent"]

    def test_both_taken_leaves_none(self, db):
        prop = PropertyFactory()
        ListingFactory(property=prop, operation_type=OperationType.SALE,
                       status=ListingStatus.DRAFT)
        ListingFactory(property=prop, operation_type=OperationType.RENT,
                       status=ListingStatus.PUBLISHED)
        ctx = _operacion_section_context(prop, FLOW_EDIT)
        assert ctx["available_operations"] == []

    def test_closed_does_not_block(self, db):
        prop = PropertyFactory()
        ListingFactory(property=prop, operation_type=OperationType.SALE,
                       status=ListingStatus.CLOSED)
        ctx = _operacion_section_context(prop, FLOW_EDIT)
        assert [v for v, _ in ctx["available_operations"]] == ["sale", "rent"]


class TestPropertyNewOperacion:
    def test_renders_operacion_section(self, auth_client, db):
        prop = PropertyFactory()
        resp = auth_client.get(reverse("properties:new_operacion", args=[prop.pk]))
        assert resp.status_code == 200
        assert 'id="operacion-section"' in resp.content.decode()

    def test_renders_with_wizard_flow(self, auth_client, db):
        prop = PropertyFactory()
        resp = auth_client.get(reverse("properties:new_operacion", args=[prop.pk]))
        assert 'name="flow" value="wizard"' in resp.content.decode()

    def test_not_found(self, auth_client, db):
        import uuid
        resp = auth_client.get(reverse("properties:new_operacion", args=[uuid.uuid4()]))
        assert resp.status_code == 404


class TestExternalSourceUpdate:
    def _url(self, source):
        return reverse("properties:external_source_update", args=[source.property.pk])

    def test_updates_source(self, auth_client, db):
        source = ExternalPropertySourceFactory(agency_name="Vieja")
        resp = auth_client.post(self._url(source), {
            "agency_name": "Nueva Inmobiliaria",
            "source_url": "https://nueva.example.com",
            "agreed_commission_percent": "4.50",
        })
        assert resp.status_code == 200
        source.refresh_from_db()
        assert source.agency_name == "Nueva Inmobiliaria"
        assert source.source_url == "https://nueva.example.com"
        assert source.agreed_commission_percent == Decimal("4.50")

    def test_blank_agency_rejected(self, auth_client, db):
        source = ExternalPropertySourceFactory(agency_name="Norte")
        resp = auth_client.post(self._url(source), {
            "agency_name": "", "source_url": "", "agreed_commission_percent": "",
        })
        assert resp.status_code == 200
        source.refresh_from_db()
        assert source.agency_name == "Norte"

    def test_blanks_source_url(self, auth_client, db):
        source = ExternalPropertySourceFactory(source_url="https://old.example.com")
        resp = auth_client.post(self._url(source), {
            "agency_name": source.agency_name, "source_url": "", "agreed_commission_percent": "",
        })
        assert resp.status_code == 200
        source.refresh_from_db()
        assert source.source_url == ""

    def test_non_external_404(self, auth_client, db):
        prop = PropertyFactory()  # is_external=False
        resp = auth_client.post(
            reverse("properties:external_source_update", args=[prop.pk]),
            {"agency_name": "X"},
        )
        assert resp.status_code == 404

    def test_get_not_allowed(self, auth_client, db):
        source = ExternalPropertySourceFactory()
        assert auth_client.get(self._url(source)).status_code == 405


class TestExternasBlockRender:
    def test_edit_shows_block_when_external(self, auth_client, db):
        source = ExternalPropertySourceFactory()
        resp = auth_client.get(reverse("properties:edit", args=[source.property.pk]))
        assert 'id="externas-section"' in resp.content.decode()

    def test_edit_hides_block_when_not_external(self, auth_client, db):
        prop = PropertyFactory()
        resp = auth_client.get(reverse("properties:edit", args=[prop.pk]))
        assert 'id="externas-section"' not in resp.content.decode()


class TestGeocodeProxy:
    @pytest.fixture(autouse=True)
    def _reset_gate(self):
        from apps.common.geocoding import _RATE_LIMIT_KEY
        cache.delete(_RATE_LIMIT_KEY)
        yield
        cache.delete(_RATE_LIMIT_KEY)

    @patch("apps.common.geocoding.httpx.get")
    def test_returns_result(self, mock_get, auth_client, db):
        resp = MagicMock()
        resp.json.return_value = [{
            "lat": "-27.45", "lon": "-58.98", "display_name": "Resistencia",
        }]
        mock_get.return_value = resp
        r = auth_client.get(reverse("geocode"), {"q": "Resistencia"})
        assert r.status_code == 200
        data = r.json()
        assert data["available"] is True
        assert data["result"]["lat"] == -27.45
        assert data["result"]["display_name"] == "Resistencia"

    @patch("apps.common.geocoding.httpx.get")
    def test_no_result(self, mock_get, auth_client, db):
        resp = MagicMock()
        resp.json.return_value = []
        mock_get.return_value = resp
        assert auth_client.get(reverse("geocode"), {"q": "xyz"}).json() == {
            "available": True, "result": None,
        }

    @patch("apps.common.geocoding.httpx.get", side_effect=httpx.TimeoutException("t"))
    def test_unavailable(self, mock_get, auth_client, db):
        assert auth_client.get(reverse("geocode"), {"q": "Resistencia"}).json() == {
            "available": False, "result": None,
        }

    def test_empty_query_returns_null(self, auth_client, db):
        assert auth_client.get(reverse("geocode"), {"q": "  "}).json() == {
            "available": True, "result": None,
        }

    def test_requires_backoffice_auth(self, client, db):
        r = client.get(reverse("geocode"), {"q": "Resistencia"})
        assert r.status_code == 302
        assert "next=/backoffice/geo/geocode/" in r.url


class TestLocationUpdate:
    def _url(self, prop):
        return reverse("properties:location_update", args=[prop.pk])

    def test_persists_point(self, auth_client, db):
        prop = PropertyFactory()
        resp = auth_client.post(self._url(prop), {"lat": "-27.4512", "lng": "-58.9866"})
        assert resp.status_code == 200
        assert resp.json() == {"saved": True}
        prop.refresh_from_db()
        assert prop.location is not None
        # el footgun, verificado: Point(x=lng, y=lat)
        assert round(prop.location.x, 4) == -58.9866   # longitud
        assert round(prop.location.y, 4) == -27.4512   # latitud

    def test_invalid_lat_rejected(self, auth_client, db):
        prop = PropertyFactory()
        resp = auth_client.post(self._url(prop), {"lat": "200", "lng": "-58.9"})
        assert resp.status_code == 400
        prop.refresh_from_db()
        assert prop.location is None

    def test_missing_coord_rejected(self, auth_client, db):
        prop = PropertyFactory()
        resp = auth_client.post(self._url(prop), {"lat": "-27.4"})
        assert resp.status_code == 400

    def test_get_not_allowed(self, auth_client, db):
        prop = PropertyFactory()
        assert auth_client.get(self._url(prop)).status_code == 405


class TestLocationSectionContext:
    def test_center_is_city_default_without_location(self, db, settings):
        settings.GEO_CITY_CENTERS = {"Resistencia": [-27.45, -58.98]}
        settings.GEO_DEFAULT_CENTER = [0.0, 0.0]
        prop = PropertyFactory(city="Resistencia", location=None)
        ctx = _location_section_context(prop)
        assert json.loads(ctx["map_center_json"]) == [-27.45, -58.98]
        assert json.loads(ctx["existing_location_json"]) is None

    def test_falls_back_to_default_for_unknown_city(self, db, settings):
        settings.GEO_CITY_CENTERS = {"Resistencia": [-27.45, -58.98]}
        settings.GEO_DEFAULT_CENTER = [-34.6, -58.4]
        prop = PropertyFactory(city="Corrientes")
        ctx = _location_section_context(prop)
        assert json.loads(ctx["map_center_json"]) == [-34.6, -58.4]

    def test_existing_location_sets_center_and_pin(self, db):
        prop = PropertyFactory(location=Point(-58.98, -27.45, srid=4326))
        ctx = _location_section_context(prop)
        assert json.loads(ctx["existing_location_json"]) == [-27.45, -58.98]  # [lat, lng]
        assert json.loads(ctx["map_center_json"]) == [-27.45, -58.98]

    def test_edit_page_includes_map(self, auth_client, db):
        prop = PropertyFactory()
        resp = auth_client.get(reverse("properties:edit", args=[prop.pk]))
        assert 'id="location-map"' in resp.content.decode()


class TestPropertyWithdrawRestore:
    def _withdraw(self, client, prop):
        return client.post(reverse("properties:withdraw", kwargs={"pk": prop.pk}))

    def _restore(self, client, prop):
        return client.post(reverse("properties:restore", kwargs={"pk": prop.pk}))

    def test_get_not_allowed(self, auth_client, db):
        prop = PropertyFactory()
        resp = auth_client.get(reverse("properties:withdraw", kwargs={"pk": prop.pk}))
        assert resp.status_code == 405

    def test_withdraw_pauses_published_and_redirects(self, auth_client, db):
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        listing = ListingFactory(property=prop, status=ListingStatus.PUBLISHED)
        resp = self._withdraw(auth_client, prop)
        assert resp.status_code == 302
        assert resp.url == reverse("properties:detail", kwargs={"pk": prop.pk})
        prop.refresh_from_db(); listing.refresh_from_db()
        assert prop.status == PropertyStatus.UNAVAILABLE
        assert listing.status == ListingStatus.PAUSED

    def test_withdraw_invalid_state_messages_and_redirects(self, auth_client, db):
        prop = PropertyFactory(status=PropertyStatus.RENTED)
        resp = auth_client.post(
            reverse("properties:withdraw", kwargs={"pk": prop.pk}), follow=True,
        )
        # Siguió el 302 hasta el detail
        assert resp.redirect_chain == [
            (reverse("properties:detail", kwargs={"pk": prop.pk}), 302)
        ]
        prop.refresh_from_db()
        assert prop.status == PropertyStatus.RENTED
        assert any(
            m.level == django_messages.ERROR for m in resp.context["messages"]
        )
    def test_restore_republishes_when_gate_passes(self, auth_client, db):
        prop = PropertyFactory(
            status=PropertyStatus.UNAVAILABLE, description="x" * 200,
        )
        PropertyMediaFactory.create_batch(5, property=prop)
        listing = ListingFactory(property=prop, status=ListingStatus.PAUSED)
        resp = self._restore(auth_client, prop)
        assert resp.status_code == 302
        prop.refresh_from_db(); listing.refresh_from_db()
        assert prop.status == PropertyStatus.AVAILABLE
        assert listing.status == ListingStatus.PUBLISHED

    def test_restore_gate_rejection_renders_checklist_and_rolls_back(self, auth_client, db):
        prop = PropertyFactory(status=PropertyStatus.UNAVAILABLE, description="corta")
        listing = ListingFactory(property=prop, status=ListingStatus.PAUSED)
        resp = self._restore(auth_client, prop)
        assert resp.status_code == 200
        codes = {item.code for item in resp.context["checklist_items"]}
        assert codes == {"photos", "description"}
        # A1: el atomic del orquestador revirtió TODO
        prop.refresh_from_db(); listing.refresh_from_db()
        assert prop.status == PropertyStatus.UNAVAILABLE
        assert listing.status == ListingStatus.PAUSED