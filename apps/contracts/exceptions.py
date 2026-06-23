class ContractValidationError(Exception):
    """Error de validación de negocio en contratos."""
    pass


class ContractDateConflict(ContractValidationError):
    """
    Las fechas del contrato solapan con otro contrato ACTIVE o SCHEDULED
    sobre la misma propiedad.
    """
    def __init__(self, message="", conflicting_contract=None):
        self.conflicting_contract = conflicting_contract
        super().__init__(message)


class InvalidContractStatus(ContractValidationError):
    """
    La operación no es válida para el estado actual del contrato.
    Cada service documenta los estados que acepta.
    """
    pass