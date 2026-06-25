"""
Contrato OUTBOUND para publicación en portales inmobiliarios.

Esta base contiene SOLO lo que la capa de orquestación (tasks) necesita para
ser agnóstica al portal: qué operaciones existen, qué devuelven, cómo se reporta
el fracaso. Todo lo portal-específico — auth, mapeo de campos, URLs, cacheo de
token, cliente HTTP — vive en cada handler concreto (ej. zonaprop.py), NUNCA acá.

Razón: ZonaProp (Navent, client_credentials) y MercadoLibre (OAuth2
authorization_code, refresh de un solo uso) difieren justo en auth. Meter
cualquier cosa portal-específica en la base la rompería al llegar el segundo
portal. La base es delgada a propósito — esa delgadez es la garantía de que no
está sobre-diseñada para una única implementación.

SCOPE V1: solo outbound (publish / unpublish). El contrato inbound (parseo de
webhooks de leads) es de forma opuesta y se define en su propia sesión, cuando
construyamos el webhook receiver. get_status queda fuera deliberadamente: el
estado llega por push (AVISO_ESTADO_PUBLICACION) y se lee desde ListingPublication,
no por polling. Ver design.md — get_status es deuda consciente ligada al inbound
(reconciliación), no un olvido.

El handler NO toca la DB. Recibe datos ya ensamblados por un selector y devuelve
un resultado estructurado que la task interpreta y persiste.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


# --------------------------------------------------------------------------
# Jerarquía de errores — el corazón del contrato.
# La task decide qué hacer según el TIPO de excepción, no según su mensaje.
# --------------------------------------------------------------------------

class PortalError(Exception):
    """Base de todo fallo de portal. No se lanza directamente — se usa una
    de las dos subclases, porque la task necesita distinguir reintentable
    de permanente."""


class PortalTransientError(PortalError):
    """Fallo REINTENTABLE: timeout, 5xx, token vencido, red caída.
    Reintentar más tarde puede tener éxito sin intervención humana.
    La task deja que Celery reintente con backoff exponencial."""


class PortalPermanentError(PortalError):
    """Fallo NO reintentable: el portal rechazó por una razón de dominio
    (validación, 4xx, campo obligatorio faltante). Reintentar no lo arregla
    — requiere que un humano corrija el dato.

    Carga el motivo concreto del rechazo (no un mensaje genérico) para que
    la task lo persista y el backoffice se lo muestre al socio no-técnico:
    'ZonaProp rechazó: falta superficie cubierta', no 'error 400'.
    """


# --------------------------------------------------------------------------
# Resultado de una publicación exitosa.
# El handler no escribe DB — devuelve esto; la task lo lee y actualiza
# ListingPublication (external_id, estado, metadata).
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class PublishResult:
    external_id: str    # id del aviso asignado por el portal (ListingPublication.external_id)
    portal_status: str  # estado que el portal reporta en el momento de la respuesta
    raw: dict           # respuesta cruda completa — va a ListingPublication.metadata para debug


# --------------------------------------------------------------------------
# Contrato outbound. Cada portal lo implementa con su auth, mapeo y cliente
# HTTP propios. ABC (no Protocol) para que un handler que olvide implementar
# una operación falle al instanciarse, no en runtime.
# --------------------------------------------------------------------------

class PortalPublisher(ABC):
    """Interfaz que la task usa para publicar en cualquier portal sin conocer
    sus detalles. El mapeo de los datos de dominio al formato del portal es
    irreductiblemente específico (idUbicacion, idTipo en Navent) y vive entero
    dentro del handler concreto — no existe un 'dict neutro' intermedio, porque
    cualquier intermedio sería el formato de un portal disfrazado."""

    @abstractmethod
    def publish(self, data) -> PublishResult:
        """Crea o modifica el aviso (upsert vía claveReferencia = listing.id).
        El upsert da idempotencia: si la task se reintenta, no se duplica el aviso.

        `data` es la estructura de lectura ensamblada por el selector
        (Listing + Property + Media + idUbicacion elegido por el socio).
        El handler la mapea al payload del portal internamente.

        Lanza:
            PortalTransientError  — si el fallo es reintentable.
            PortalPermanentError  — si el portal rechazó por razón de dominio.
        """
        ...

    @abstractmethod
    def unpublish(self, external_id: str) -> None:
        """Despublica el aviso identificado por external_id (el id asignado por
        el portal, guardado en ListingPublication). Mismas reglas de excepción
        que publish. No devuelve nada: el éxito es la ausencia de excepción."""
        ...