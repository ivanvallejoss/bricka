class AuditViolationError(Exception):
    """
    Tira excepcion cuando una operacion intenta hacer un bulk sobre un modelo auditable.
    Esto sucede porque las operaciones bulk saltean las signals de Django y generan un bug silencioso en el audit log.

    Chequear cual es el servicio correspondiente para el caso que se necesita
    docs/convention/audit.md
    """