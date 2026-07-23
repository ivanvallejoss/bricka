"""
Tests de la limpieza de huérfanos R2 (S4, tajada obs. #7).
I/O de R2 por el borde de S1: se stubea storage._client completo.
"""
from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.common import storage
from apps.properties.tests.factories import PropertyFactory, PropertyMediaFactory


def _stub_bucket(monkeypatch, settings, objects, bucket="bricka-media-dev"):
    """Stub del borde S1: paginator de list_objects_v2 con una página."""
    settings.R2_PUBLIC_MEDIA_BUCKET = bucket
    client = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = [{"Contents": objects}] if objects else [{}]
    client.get_paginator.return_value = paginator
    monkeypatch.setattr(storage, "_client", lambda: client)
    return client


def _obj(key, minutes_old=60):
    return {"Key": key, "LastModified": timezone.now() - timedelta(minutes=minutes_old)}


class TestListPublicMediaObjects:
    def test_yields_key_and_last_modified_across_pages(self, monkeypatch, settings):
        settings.R2_PUBLIC_MEDIA_BUCKET = "bricka-media-dev"
        client = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"Contents": [_obj("properties/a/1.jpg")]},
            {"Contents": [_obj("properties/b/2.jpg")]},
        ]
        client.get_paginator.return_value = paginator
        monkeypatch.setattr(storage, "_client", lambda: client)

        got = list(storage.list_public_media_objects(prefix="properties/"))
        assert [o["key"] for o in got] == ["properties/a/1.jpg", "properties/b/2.jpg"]
        assert all("last_modified" in o for o in got)
        paginator.paginate.assert_called_once_with(
            Bucket="bricka-media-dev", Prefix="properties/",
        )

    def test_empty_bucket_yields_nothing(self, monkeypatch, settings):
        _stub_bucket(monkeypatch, settings, [])
        assert list(storage.list_public_media_objects()) == []


class TestCleanupGuards:
    def test_refuses_without_debug(self, db, monkeypatch, settings):
        settings.DEBUG = False
        settings.R2_PUBLIC_MEDIA_BUCKET = "bricka-media-dev"
        client = _stub_bucket(monkeypatch, settings, [_obj("properties/x/h.jpg")])
        with pytest.raises(CommandError, match="DEBUG"):
            call_command("cleanup_r2_orphans")
        client.delete_object.assert_not_called()

    def test_refuses_non_dev_bucket(self, db, monkeypatch, settings):
        settings.DEBUG = True
        client = _stub_bucket(
            monkeypatch, settings, [_obj("properties/x/h.jpg")], bucket="bricka-media",
        )
        with pytest.raises(CommandError, match="-dev"):
            call_command("cleanup_r2_orphans")
        client.delete_object.assert_not_called()


class TestCleanupDiff:
    def test_deletes_orphans_retains_db_and_grace(self, db, monkeypatch, settings):
        settings.DEBUG = True
        media = PropertyMediaFactory()  # con fila en DB -> retenido
        objects = [
            _obj(media.r2_key),                                  # retenido: DB
            _obj("properties/viejo/huerfano.jpg"),               # eliminado
            _obj("properties/nuevo/en-vuelo.jpg", minutes_old=1),  # retenido: gracia
        ]
        client = _stub_bucket(monkeypatch, settings, objects)

        out = StringIO()
        call_command("cleanup_r2_orphans", stdout=out)

        client.delete_object.assert_called_once_with(
            Bucket="bricka-media-dev", Key="properties/viejo/huerfano.jpg",
        )
        salida = out.getvalue()
        assert "3 listados" in salida
        assert "2 retenidos" in salida
        assert "1 con fila en DB" in salida
        assert "1 por gracia" in salida
        assert "1 eliminados" in salida

    def test_grace_window_is_configurable(self, db, monkeypatch, settings):
        settings.DEBUG = True
        client = _stub_bucket(
            monkeypatch, settings, [_obj("properties/x/reciente.jpg", minutes_old=5)],
        )
        call_command("cleanup_r2_orphans", grace_minutes=0)
        client.delete_object.assert_called_once()

    def test_double_seed_cycle_semantics(self, db, monkeypatch, settings):
        """
        El ciclo doble en miniatura: keys del ciclo 1 (huérfanas tras el
        truncado) se eliminan; keys del ciclo 2 (fila en DB) se retienen.
        """
        settings.DEBUG = True
        vivos = [PropertyMediaFactory() for _ in range(2)]
        objects = [_obj(m.r2_key) for m in vivos] + [
            _obj("properties/ciclo1/a.jpg"), _obj("properties/ciclo1/b.jpg"),
        ]
        client = _stub_bucket(monkeypatch, settings, objects)

        call_command("cleanup_r2_orphans")

        borradas = {c.kwargs["Key"] for c in client.delete_object.call_args_list}
        assert borradas == {"properties/ciclo1/a.jpg", "properties/ciclo1/b.jpg"}
        