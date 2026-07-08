class ListingValidationError(Exception):
    pass


class ListingPublicationRequirementsError(ListingValidationError):
    """
    El listing no cumple los requisitos de publicación (gate).
    missing: códigos estables de requisito incumplido — contrato con
    cualquier UI (form, API futura). La UI mapea código → mensaje.
    Hereda de ListingValidationError: los except existentes la atrapan;
    quien necesita el detalle estructurado atrapa la subclase.
    """

    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(
            f"Requisitos de publicación incumplidos: {', '.join(missing)}"
        )