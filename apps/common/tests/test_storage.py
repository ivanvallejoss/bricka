import re
from io import BytesIO
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from apps.common import storage
from apps.common.storage import (
    _safe_extension,
    build_document_key,
    build_media_key,
    delete_private_document,
    delete_public_media,
    generate_document_download_url,
    generate_media_upload_url,
    get_public_media_url,
    public_media_exists,
    upload_private_document,
    upload_public_media,
)

UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


@pytest.fixture
def stub_client(monkeypatch):
    """
    Borde de mocking acordado (S1): se reemplaza el factory _client
    completo — el único punto de contacto con boto3. Aguas arriba todo
    corre real; boto3 no se re-testea. testing.md prohíbe mocks de ORM,
    no de I/O externo.
    """
    client = MagicMock()
    monkeypatch.setattr(storage, "_client", lambda: client)
    return client


@pytest.fixture
def r2_settings(settings):
    settings.R2_PUBLIC_MEDIA_BUCKET = "media-test"
    settings.R2_PRIVATE_DOCS_BUCKET = "docs-test"
    settings.R2_PUBLIC_MEDIA_BASE_URL = "https://cdn.test"
    return settings


class TestSafeExtension:
    def test_returns_lowercase_extension_with_dot(self):
        assert _safe_extension("FOTO.JPG") == ".jpg"

    def test_returns_empty_string_when_no_extension(self):
        assert _safe_extension("archivo_sin_extension") == ""

    def test_returns_last_suffix_for_double_extension(self):
        assert _safe_extension("backup.tar.gz") == ".gz"


class TestBuildKeys:
    def test_media_key_matches_contract_format(self):
        property_id = uuid4()
        key = build_media_key(property_id=property_id, filename="foto.JPG")
        assert re.fullmatch(
            rf"properties/{property_id}/{UUID_RE}\.jpg", key
        )

    def test_document_key_matches_contract_format(self):
        document_id = uuid4()
        key = build_document_key(document_id=document_id, filename="escritura.pdf")
        assert re.fullmatch(
            rf"documents/{document_id}/{UUID_RE}\.pdf", key
        )

    def test_media_key_is_unique_per_call(self):
        property_id = uuid4()
        first = build_media_key(property_id=property_id, filename="foto.jpg")
        second = build_media_key(property_id=property_id, filename="foto.jpg")
        assert first != second


class TestPublicMediaUrl:
    def test_concatenates_base_url_and_key(self, r2_settings):
        url = get_public_media_url("properties/x/y.jpg")
        assert url == "https://cdn.test/properties/x/y.jpg"


class TestUploads:
    def test_public_media_uploads_to_public_bucket(self, stub_client, r2_settings):
        fileobj = BytesIO(b"data")
        upload_public_media(
            key="properties/x/y.jpg", fileobj=fileobj, content_type="image/jpeg"
        )
        stub_client.upload_fileobj.assert_called_once_with(
            fileobj,
            "media-test",
            "properties/x/y.jpg",
            ExtraArgs={"ContentType": "image/jpeg"},
        )

    def test_private_document_uploads_to_private_bucket(
        self, stub_client, r2_settings
    ):
        fileobj = BytesIO(b"data")
        upload_private_document(
            key="documents/x/y.pdf", fileobj=fileobj, content_type="application/pdf"
        )
        stub_client.upload_fileobj.assert_called_once_with(
            fileobj,
            "docs-test",
            "documents/x/y.pdf",
            ExtraArgs={"ContentType": "application/pdf"},
        )


class TestGenerateDocumentDownloadUrl:
    def test_requests_presigned_url_with_default_expiration(
        self, stub_client, r2_settings
    ):
        stub_client.generate_presigned_url.return_value = "https://signed.test/x"
        url = generate_document_download_url("documents/x/y.pdf")
        stub_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "docs-test", "Key": "documents/x/y.pdf"},
            ExpiresIn=300,
        )
        assert url == "https://signed.test/x"

    def test_respects_custom_expiration(self, stub_client, r2_settings):
        generate_document_download_url("documents/x/y.pdf", expires_in=60)
        _, kwargs = stub_client.generate_presigned_url.call_args
        assert kwargs["ExpiresIn"] == 60


class TestDeletes:
    def test_public_media_deletes_from_public_bucket(self, stub_client, r2_settings):
        delete_public_media("properties/x/y.jpg")
        stub_client.delete_object.assert_called_once_with(
            Bucket="media-test", Key="properties/x/y.jpg"
        )

    def test_private_document_deletes_from_private_bucket(
        self, stub_client, r2_settings
    ):
        delete_private_document("documents/x/y.pdf")
        stub_client.delete_object.assert_called_once_with(
            Bucket="docs-test", Key="documents/x/y.pdf"
        )

    def test_delete_raises_when_client_fails(self, stub_client, r2_settings):
        """Pin del ADR 'delete lanza, no traga': habilita R2-primero-DB-después."""
        stub_client.delete_object.side_effect = RuntimeError("boom")
        with pytest.raises(RuntimeError):
            delete_public_media("properties/x/y.jpg")


class TestGenerateMediaUploadUrl:
    def test_signs_put_with_content_type_in_signature(self, stub_client, r2_settings):
        stub_client.generate_presigned_url.return_value = "https://signed.test/put"
        url = generate_media_upload_url(
            key="properties/x/y.jpg", content_type="image/jpeg"
        )
        stub_client.generate_presigned_url.assert_called_once_with(
            "put_object",
            Params={
                "Bucket": "media-test",
                "Key": "properties/x/y.jpg",
                "ContentType": "image/jpeg",
            },
            ExpiresIn=300,
        )
        assert url == "https://signed.test/put"

    def test_respects_custom_expiration(self, stub_client, r2_settings):
        generate_media_upload_url(
            key="properties/x/y.jpg", content_type="image/jpeg", expires_in=120
        )
        _, kwargs = stub_client.generate_presigned_url.call_args
        assert kwargs["ExpiresIn"] == 120


class TestPublicMediaExists:
    @staticmethod
    def _head_error(status: int) -> ClientError:
        return ClientError(
            {
                "Error": {"Code": str(status), "Message": "x"},
                "ResponseMetadata": {"HTTPStatusCode": status},
            },
            "HeadObject",
        )

    def test_returns_true_when_object_exists(self, stub_client, r2_settings):
        stub_client.head_object.return_value = {"ContentLength": 123}
        assert public_media_exists("properties/x/y.jpg") is True
        stub_client.head_object.assert_called_once_with(
            Bucket="media-test", Key="properties/x/y.jpg"
        )

    def test_returns_false_when_object_missing(self, stub_client, r2_settings):
        stub_client.head_object.side_effect = self._head_error(404)
        assert public_media_exists("properties/x/missing.jpg") is False

    def test_propagates_non_404_client_error(self, stub_client, r2_settings):
        stub_client.head_object.side_effect = self._head_error(403)
        with pytest.raises(ClientError):
            public_media_exists("properties/x/forbidden.jpg")