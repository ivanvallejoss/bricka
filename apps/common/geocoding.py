# apps/common/geocoding.py
"""
Geocoding (dirección → coordenadas) contra Nominatim (OpenStreetMap). Único punto
de contacto con el servicio. Espeja storage.py: cliente fino a un externo en
common/, sin lógica de presentación ni de negocio — solo geocodificar.

Por qué existe (y por qué NO se llama desde el browser):
  - User-Agent: la política de Nominatim exige un UA identificable con contacto;
    banea los genéricos. Se setea uno controlado (settings.NOMINATIM_USER_AGENT).
  - Rate limit 1 req/s: techo absoluto de la política, solo enforzable centralizado.
    _acquire_slot es un gate atómico global (Redis SETNX con expiry 1s) que entra
    una vez por ventana a través de todos los workers.
  - Provider swap: el consumidor nunca sabe que es Nominatim; se cambia acá.

Contrato — tres estados, sin filtrar detalles del transporte al caller:
  - GeocodeResult   → match.
  - None            → query válida, 0 resultados.
  - GeocodeUnavailable (excepción) → timeout, red, HTTP, o el gate rechazó. El
    view lo traduce a "no disponible"; el frontend cae a centro default + pin
    manual. NUNCA bloquea al usuario.

Nota vs storage.py: storage.py cachea el cliente boto3 con @lru_cache. Acá se usa
la API funcional de httpx en vez de un Client cacheado: a 1 req/s el pooling es
irrelevante, y el cliente cacheado pelearía con el mock del borde HTTP en los
tests. Se espeja la estructura (funciones en common, settings, docstrings), no
ese detalle.
"""
from dataclasses import dataclass

import httpx
from django.conf import settings
from django.core.cache import cache


_RATE_LIMIT_KEY = "geo:nominatim:slot"
_RATE_LIMIT_WINDOW = 1  # segundos — techo de la política de Nominatim


class GeocodeUnavailable(Exception):
    """El geocoding no respondió (timeout, red, HTTP, o rate-gate). Nunca bloquea."""


@dataclass(frozen=True)
class GeocodeResult:
    lat: float
    lon: float
    display_name: str


def _acquire_slot() -> bool:
    """Gate atómico de 1 req/s, global entre workers. cache.add (SETNX) solo
    escribe si la key no existe → True una vez por ventana; el expiry la libera."""
    return cache.add(_RATE_LIMIT_KEY, True, timeout=_RATE_LIMIT_WINDOW)


def geocode_address(query: str) -> GeocodeResult | None:
    """
    Geocodifica una dirección. Sesga a Argentina (countrycodes=ar), un resultado.
    Devuelve GeocodeResult, None (sin match), o levanta GeocodeUnavailable.
    """
    if not _acquire_slot():
        raise GeocodeUnavailable("rate limit — slot consumido en esta ventana")

    try:
        response = httpx.get(
            f"{settings.NOMINATIM_BASE_URL}/search",
            params={"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "ar"},
            headers={"User-Agent": settings.NOMINATIM_USER_AGENT},
            timeout=settings.NOMINATIM_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise GeocodeUnavailable(str(exc)) from exc

    if not data:
        return None

    hit = data[0]
    return GeocodeResult(
        lat=float(hit["lat"]),
        lon=float(hit["lon"]),
        display_name=hit.get("display_name", ""),
    )