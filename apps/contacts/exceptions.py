class ContactHasOpenDeals(Exception):
    """
    Se lanza al intentar archivar un contacto con negociaciones abiertas.
    """
    def __str__(self):
        return "No se puede archivar un contacto con negociaciones activas."