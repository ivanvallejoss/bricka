class DealValidationError(Exception):
    """Error de validación de negocio en deals."""
    pass


class DealAlreadyClosed(DealValidationError):
    """
    El deal ya tiene un outcome asignado.
    Los deals son terminales en V1 — no existe reopen.
    """
    pass