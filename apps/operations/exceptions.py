"""
Excepciones del módulo de coordinación.

Vacío en la Unidad 1: el orquestador todavía no rechaza ninguna transición.
El guard que bloquea el deslizamiento silencioso desde SOLD (paso 3 del orden
de implementación) definirá acá su excepción propia.
"""


class InvalidPropertyTransition(Exception):
    """
    Se intentó una transición de estado de propiedad desde un estado origen que
    no la admite: p. ej. withdraw sobre una propiedad que no está AVAILABLE,
    restore sobre una que no está UNAVAILABLE, o remandate sobre una que no está
    SOLD.

    La reusa el guard de deslizamiento silencioso desde SOLD (paso 3).
    """
    pass