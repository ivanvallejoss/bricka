import json
from unittest.mock import MagicMock

import pytest
from django.urls import reverse

from apps.common import storage
from apps.properties.services import MAX_PHOTOS_PER_PROPERTY
from apps.properties.tests.factories import PropertyFactory, PropertyMediaFactory


@pytest.fixture
def stub_r2(monkeypatch, settings):
    """Borde R2 (S1): se stubea storage._client; la firma no toca boto3 real."""
    settings.R2_PUBLIC_MEDIA_BUCKET = "media-test"
    client = MagicMock()
    client.generate_presigned_url.return_value = "https://signed.test/put"
    monkeypatch.setattr(storage, "_client", lambda: client)
    return client


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