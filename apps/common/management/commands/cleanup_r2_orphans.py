"""
Limpieza de huérfanos del bucket de media dev (tajada de la obs. #7, S4).

Huérfano: objeto en el bucket público de media SIN fila PropertyMedia con esa
key, y más viejo que la ventana de gracia. La definición es atemporal — vale
igual corriendo suelto o invocado por el reset del seed. La política GENERAL
de borrado de media (cascadas de dominio, soft-delete de propiedad, producción)
NO se decide acá: sigue capturada para la ventana de planificación.

Ventana de gracia: un presigned PUT completado cuyo confirm todavía no corrió
es un objeto sin fila — huérfano *aparente* por unos segundos. Los objetos más
nuevos que --grace-minutes se retienen y reportan.

GUARDS (primera operación destructiva sobre un bucket del codebase — ver ADR):
  1. settings.DEBUG debe estar activo.
  2. R2_PUBLIC_MEDIA_BUCKET debe terminar en '-dev'.
Si cualquiera falla, la limpieza NO corre y lo dice (CommandError). Un --reset
jamás debe poder vaciar un bucket de producción por un .env equivocado.
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.common.storage import delete_public_media, list_public_media_objects
from apps.properties.models import PropertyMedia

MEDIA_PREFIX = "properties/"
DEFAULT_GRACE_MINUTES = 10


class Command(BaseCommand):
    help = (
        "Elimina del bucket de media DEV los objetos huérfanos (sin fila "
        "PropertyMedia). Solo corre con DEBUG y contra un bucket '-dev'."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--grace-minutes", type=int, default=DEFAULT_GRACE_MINUTES,
            help=(
                "Retener objetos más nuevos que esta ventana (uploads en "
                f"vuelo, pre-confirm). Default: {DEFAULT_GRACE_MINUTES}."
            ),
        )

    def handle(self, *args, **options):
        self._check_guards()

        db_keys = set(PropertyMedia.objects.values_list("r2_key", flat=True))
        cutoff = timezone.now() - timedelta(minutes=options["grace_minutes"])

        listed = retained_db = retained_grace = deleted = 0
        for obj in list_public_media_objects(prefix=MEDIA_PREFIX):
            listed += 1
            if obj["key"] in db_keys:
                retained_db += 1
            elif obj["last_modified"] > cutoff:
                retained_grace += 1
            else:
                delete_public_media(obj["key"])
                deleted += 1

        self.stdout.write(self.style.SUCCESS(
            f"✓ Limpieza R2 ({settings.R2_PUBLIC_MEDIA_BUCKET}): "
            f"{listed} listados / "
            f"{retained_db + retained_grace} retenidos "
            f"({retained_db} con fila en DB, {retained_grace} por gracia) / "
            f"{deleted} eliminados."
        ))

    def _check_guards(self):
        if not settings.DEBUG:
            raise CommandError(
                "Limpieza R2 deshabilitada fuera de DEBUG: es una operación "
                "destructiva sobre un bucket."
            )
        if not settings.R2_PUBLIC_MEDIA_BUCKET.endswith("-dev"):
            raise CommandError(
                "Limpieza R2 deshabilitada: el bucket configurado "
                f"('{settings.R2_PUBLIC_MEDIA_BUCKET}') no termina en '-dev'. "
                "Este comando solo opera sobre el bucket de desarrollo."
            )