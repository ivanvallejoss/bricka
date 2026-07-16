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
from botocore.exceptions import ClientError
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


def generate_media_upload_url(
    *, key: str, content_type: str, expires_in: int = 300
) -> str:
    """Presigned PUT de corta vida (default 5 min) para subir una foto
    directo del browser a R2, sin pasar por Django.

    ContentType va DENTRO de la firma: boto3 lo agrega a los SignedHeaders
    de SigV4, así que R2 acepta el PUT solo si el header Content-Type del
    browser coincide EXACTO con content_type. Un cliente que declare otro
    tipo produce SignatureDoesNotMatch (403) — el MIME que el server validó
    es el único que R2 acepta.

    No valida los bytes: liga el Content-Type declarado, no lo infiere del
    contenido. La certeza de que el objeto llegó la da el head_object del
    confirm (public_media_exists), no esta firma.

    Precondición: el caller (view de sign) ya validó MIME/tamaño/techo y,
    si hubo resize, content_type ya es el del archivo final."""
    return _client().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.R2_PUBLIC_MEDIA_BUCKET,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
    )


def public_media_exists(key: str) -> bool:
    """head_object contra el bucket público: ¿el objeto ya está subido?

    Es la precondición del confirm — antes de registrar PropertyMedia, el
    server verifica que el PUT del browser realmente llegó a R2, en vez de
    confiar en que el cliente dice "lo subí".

    Semántica de errores (el fino de esta función):
      - 404 → el objeto no está → False. Es el único "no" legítimo: el
        confirm lo lee como "la foto falló" y la marca para reintento.
      - cualquier otro ClientError (403 de credenciales, red, 5xx) PROPAGA.
        No es ausencia, es un problema real del server; tragarlo como False
        haría que un token vencido se vea igual que un upload que nunca
        ocurrió, y el usuario reintentaría contra una pared invisible.

    HEAD no trae body, así que el status HTTP es la señal autoritativa:
    Error.Code varía entre implementaciones S3-compatibles, el status no."""
    try:
        _client().head_object(Bucket=settings.R2_PUBLIC_MEDIA_BUCKET, Key=key)
        return True
    except ClientError as exc:
        if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
            return False
        raise


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
    endpoint S3 de R2 — los documentos nunca van por custom domain.

    ⚠️ Las presigned URLs no se cachean — cada render de la view genera
    URLs nuevas. Si una vista lista muchos documentos y se vuelve lenta,
    cachear a nivel de view con TTL < expires_in."""
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.R2_PRIVATE_DOCS_BUCKET, "Key": key},
        ExpiresIn=expires_in,
    )


def delete_private_document(key: str) -> None:
    """Borra de R2. Lanza si falla — habilita el patrón 'R2 primero, DB después'
    documentado: si esto explota, el service nunca llega al delete de DB."""
    _client().delete_object(Bucket=settings.R2_PRIVATE_DOCS_BUCKET, Key=key)
