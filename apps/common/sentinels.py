from typing import Any


class _Unset:
    """
    Sentinela para distinguir "parámetro no enviado" de "valor None/vacío".

    Uso en services de escritura con semántica parcial:
        def update_x(*, campo: int | None = UNSET):
            if campo is not UNSET:
                ...  # campo trae un valor real, incluido None (= blanquear)

    None y "" son VALORES del dominio (null en DB / string vacío);
    UNSET significa "el caller no opinó sobre este campo".
    """

    def __repr__(self):
        return "UNSET"


UNSET: Any = _Unset()