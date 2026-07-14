"""
Smoke test de R2: round-trip real contra los buckets del .env activo.

Valida: credenciales del token, base URL pública de media, presigned
de documentos, privacidad del bucket de documentos (GET sin firma debe
fallar) y que los deletes borran de verdad.

Uso: python manage.py r2_smoke
Dev: buckets *-dev. En S10 se corre igual contra el .env de prod.
NO valida CORS (eso es del browser, llega en S3).
"""
from io import BytesIO
from uuid import uuid4

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.common.storage import (
    build_document_key,
    build_media_key,
    delete_private_document,
    delete_public_media,
    generate_document_download_url,
    get_public_media_url,
    upload_private_document,
    upload_public_media,
)


class Command(BaseCommand):
    help = "Round-trip de smoke contra los buckets R2 del .env activo."

    def handle(self, *args, **options):
        marker = f"bricka-r2-smoke-{uuid4()}".encode()
        media_key = build_media_key(property_id=uuid4(), filename="smoke.txt")
        doc_key = build_document_key(document_id=uuid4(), filename="smoke.txt")
        media_uploaded = False
        doc_uploaded = False

        try:
            # ── Media (bucket público) ──────────────────────────────
            self._step("upload a bucket público")
            upload_public_media(
                key=media_key, fileobj=BytesIO(marker), content_type="text/plain"
            )
            media_uploaded = True

            self._step("GET de URL pública (base URL r2.dev)")
            public_url = get_public_media_url(media_key)
            resp = httpx.get(public_url, timeout=15)
            self._expect(
                resp.status_code == 200 and resp.content == marker,
                f"GET {public_url} → {resp.status_code} "
                f"(esperado 200 con el payload exacto)",
            )

            # ── Documents (bucket privado) ──────────────────────────
            self._step("upload a bucket privado")
            upload_private_document(
                key=doc_key, fileobj=BytesIO(marker), content_type="text/plain"
            )
            doc_uploaded = True

            self._step("GET de presigned URL (default 300s)")
            signed_url = generate_document_download_url(doc_key)
            resp = httpx.get(signed_url, timeout=15)
            self._expect(
                resp.status_code == 200 and resp.content == marker,
                f"GET presigned → {resp.status_code} "
                f"(esperado 200 con el payload exacto)",
            )

            self._step("GET SIN firma al bucket privado (debe fallar)")
            unsigned_url = (
                f"{settings.R2_ENDPOINT_URL}/"
                f"{settings.R2_PRIVATE_DOCS_BUCKET}/{doc_key}"
            )
            resp = httpx.get(unsigned_url, timeout=15)
            # R2 responde 400 a requests sin header Authorization (no 403
            # como AWS): sin firma, el request es malformado, no denegado.
            # Cualquier 400/401/403 prueba que el bucket no sirve contenido
            # sin firma. Un 200 acá es incidente; cualquier otro código es
            # anomalía a investigar.
            self._expect(
                resp.status_code in (400, 401, 403),
                f"GET sin firma → {resp.status_code}. Si es 200 el bucket "
                f"de documentos quedó público: INCIDENTE, revisar consola R2.",
            )

            # ── Deletes ─────────────────────────────────────────────
            self._step("delete de media + verificación 404")
            delete_public_media(media_key)
            media_uploaded = False
            resp = httpx.get(public_url, timeout=15)
            self._expect(
                resp.status_code == 404,
                f"GET post-delete → {resp.status_code} (esperado 404)",
            )

            self._step("delete de documento")
            delete_private_document(doc_key)
            doc_uploaded = False

        finally:
            # Cleanup best-effort: no dejar basura si algo falló a mitad.
            if media_uploaded:
                try:
                    delete_public_media(media_key)
                except Exception:
                    self.stderr.write(f"⚠️ limpiar a mano: {media_key} (media)")
            if doc_uploaded:
                try:
                    delete_private_document(doc_key)
                except Exception:
                    self.stderr.write(f"⚠️ limpiar a mano: {doc_key} (documents)")

        self.stdout.write(self.style.SUCCESS(
            "R2 smoke OK — credenciales, URL pública, presigned, "
            "privacidad de documents y deletes verificados."
        ))

    # ── Helpers ─────────────────────────────────────────────────────
    def _step(self, message: str) -> None:
        self.stdout.write(f"→ {message}")

    def _expect(self, condition: bool, detail: str) -> None:
        if not condition:
            raise CommandError(detail)