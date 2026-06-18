from django.conf import settings

_s3_client = None


def _get_s3_client():
    """
    Cliente boto3 instanciado una sola vez por proceso (singleton por worker).

    En producción con gunicorn cada worker tiene su propia instancia —
    correcto, no hay estado compartido entre requests.
    boto3 maneja reconexión interna si la conexión cae.
    """
    global _s3_client
    if _s3_client is None:
        import boto3
        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )
    return _s3_client


def build_media_url(r2_key: str) -> str:
    """
    URL pública para media de propiedades (fotos, cover).
    El bucket de media es público — no requiere firma.

    Uso: foto cover en listado de propiedades, galería en detalle.
    """
    return f"{settings.R2_PUBLIC_BASE_URL}/{r2_key}"


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


def categorize_document(content_type: str) -> str:
    """
    Categoría visual para el template, derivada del content_type del archivo.
    Retorna: 'image' | 'pdf' | 'word' | 'other'
    """
    if content_type.startswith("image/"):
        return "image"
    if content_type == "application/pdf":
        return "pdf"
    if "word" in content_type or content_type == "application/msword":
        return "word"
    return "other"