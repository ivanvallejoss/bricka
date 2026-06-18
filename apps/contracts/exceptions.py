class ContractValidationError(Exception):
    """Error de validación de negocio en contratos."""
    pass


class ContractDateConflict(ContractValidationError):
    """
    Las fechas del contrato solapan con otro contrato ACTIVE o SCHEDULED
    sobre la misma propiedad.
    """
    pass


class InvalidContractStatus(ContractValidationError):
    """
    La operación no es válida para el estado actual del contrato.
    Cada service documenta los estados que acepta.
    """
    pass