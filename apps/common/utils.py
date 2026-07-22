from django.db import IntegrityError


# Sentinel para distinguir "no enviado" de None en updates parciales.
# Usar cuando None es un valor de negocio válido que no debe confundirse
# con "el caller no envió este campo".
#
# Ejemplo canónico — update_deal:
#   agent_id=None  → desasignar agente explícitamente
#   agent_id=UNSET → campo no enviado, no modificar
UNSET = object()


def violates_constraint(exc: IntegrityError, constraint_name: str) -> bool:
    """Identifica si el IntegrityError fue disparado por un constraint
    específico, vía el diagnóstico de Postgres — NO parseando el mensaje
    de error como string. psycopg2/psycopg exponen .diag.constraint_name
    en la excepción subyacente que Django envuelve como __cause__.

    Pieza del patrón chequeo-en-service + constraint-en-DB + catch:
    el catch usa esto para traducir la violación cruda al error de
    negocio del módulo. Primeras instancias: billing (recibos
    periódicos), listings (unicidad por operación).
    """
    diag = getattr(exc.__cause__, "diag", None)
    return getattr(diag, "constraint_name", None) == constraint_name