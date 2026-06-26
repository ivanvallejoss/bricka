# apps/common/storage.py
"""
Acceso a R2 y generación de URLs. Único punto de contacto con el object store.

NO contiene lógica de presentación ni categorización de archivos
(eso vive en documents/utils.py). Solo: subir, generar URL, borrar.

Dos buckets con modelos de acceso opuestos:
  - PÚBLICO  (R2_PUBLIC_MEDIA_BUCKET): fotos de propiedades. URL pública
    estable vía custom domain. Sin firma. La consume el handler de portales.
  - PRIVADO  (R2_PRIVATE_DOCS_BUCKET): documentos legales. Solo presigned URLs
    de corta vida. Nunca acceso público.

El bucket NO se almacena por fila — se deriva del modelo. PropertyMedia
siempre usa las funciones *_public_media; Document siempre las *_private_document.
La elección de bucket es explícita en el nombre de la función, no un
parámetro que se pueda equivocar.
"""
from functools import lru_cache
from pathlib import PurePosixPath
from uuid import UUID, uuid4

import boto3
from botocore.config import Config
from django.conf import settings


@lru_cache(maxsize=1)
def _client():
    """Cliente S3 compartido — R2 es S3-compatible.
    region_name='auto' y signature s3v4 son requeridos por R2.
    Bajo Celery prefork cada worker cachea su propio cliente — correcto."""
    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def _safe_extension(filename: str) -> str:
    """Extensión en minúscula, incluyendo el punto (ej '.jpg'). '' si no tiene."""
    return PurePosixPath(filename).suffix.lower()


# --------------------------------------------------------------------------
# Bucket público — media de marketing (PropertyMedia)
# --------------------------------------------------------------------------

def build_media_key(*, property_id: UUID, filename: str) -> str:
    """properties/{property_id}/{uuid4}{ext}
    Prefijo legible para operación; leaf con UUID propio, no adivinable."""
    return f"properties/{property_id}/{uuid4()}{_safe_extension(filename)}"


def upload_public_media(*, key: str, fileobj, content_type: str) -> None:
    _client().upload_fileobj(
        fileobj,
        settings.R2_PUBLIC_MEDIA_BUCKET,
        key,
        ExtraArgs={"ContentType": content_type},
    )


def get_public_media_url(key: str) -> str:
    """URL pública estable vía custom domain. Pura concatenación de string —
    sin llamada a API, sin firma, sin expiración.
    Es la URL exacta que el handler entrega a Navent en multimedia.imagenes."""
    return f"{settings.R2_PUBLIC_MEDIA_BASE_URL}/{key}"


def delete_public_media(key: str) -> None:
    """Borra de R2. Lanza si falla — el caller decide el orden DB/R2."""
    _client().delete_object(Bucket=settings.R2_PUBLIC_MEDIA_BUCKET, Key=key)


# --------------------------------------------------------------------------
# Bucket privado — documentos legales (Document)
# --------------------------------------------------------------------------

def build_document_key(*, document_id: UUID, filename: str) -> str:
    """documents/{document_id}/{uuid4}{ext} — agrupado por documento
    para findability operativa en R2."""
    return f"documents/{document_id}/{uuid4()}{_safe_extension(filename)}"


def upload_private_document(*, key: str, fileobj, content_type: str) -> None:
    _client().upload_fileobj(
        fileobj,
        settings.R2_PRIVATE_DOCS_BUCKET,
        key,
        ExtraArgs={"ContentType": content_type},
    )


def generate_document_download_url(key: str, *, expires_in: int = 300) -> str:
    """Presigned URL de corta vida (default 5 min). Se genera en el momento
    en que un humano abre el documento en el backoffice. Sirve sobre el
    endpoint S3 de R2 — los documentos nunca van por custom domain."""
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.R2_PRIVATE_DOCS_BUCKET, "Key": key},
        ExpiresIn=expires_in,
    )


def delete_private_document(key: str) -> None:
    """Borra de R2. Lanza si falla — habilita el patrón 'R2 primero, DB después'
    documentado: si esto explota, el service nunca llega al delete de DB."""
    _client().delete_object(Bucket=settings.R2_PRIVATE_DOCS_BUCKET, Key=key)


#
#   OLD CONFIG
#

def generate_document_url(r2_key: str, expiration: int = 900) -> str:
    """
    URL de acceso a un documento legal.
    Dev:  URL local via MEDIA_URL — no requiere credenciales R2.
    Prod: signed URL de R2 con expiración (default 15 minutos).

    ⚠️ Las signed URLs no se cachean — cada render de la view genera
    URLs nuevas. Para vistas con muchos documentos, cachear a nivel
    de view con TTL < ExpiresIn.

    ExpiresIn=900: suficiente para abrir/descargar, corto para que
    el link no circule si alguien lo copia.
    """
    if settings.DEBUG:
        return f"{settings.MEDIA_URL}{r2_key}"
    return _get_s3_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
            "Key": r2_key,
        },
        ExpiresIn=expiration,
    )


def build_media_url(r2_key: str) -> str:
    """
    URL pública para media de propiedades (fotos, cover).
    El bucket de media es público — no requiere firma.
    Uso: foto cover en listado de propiedades, galería en detalle.
    """
    return f"{settings.R2_PUBLIC_BASE_URL}/{r2_key}"