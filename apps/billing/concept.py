from dataclasses import dataclass, asdict
from decimal import Decimal

from .choices import ConceptLineType
from .exceptions import InvalidConceptLine  # excepción de negocio, la agrego a exceptions.py


@dataclass(frozen=True)
class ConceptLine:
    """Renglón del desglose de un comprobante. Amount SIEMPRE positivo —
    la dirección la define el type al computar el total (ver _compute_total).
    """
    type: str
    description: str
    amount: Decimal
    contract_id: str | None = None  # presente solo en renglones de OWNER_STATEMENT

    def __post_init__(self):
        if self.amount <= 0:
            raise InvalidConceptLine("El amount de un renglón debe ser positivo.")
        if self.type in (ConceptLineType.OTHER_CHARGE, ConceptLineType.OTHER_CREDIT) \
                and not self.description.strip():
            raise InvalidConceptLine(
                "Un renglón OTHER_CHARGE/OTHER_CREDIT exige description no vacío."
            )

    def to_json(self) -> dict:
        d = asdict(self)
        d["amount"] = str(self.amount)  # Decimal → string, como en _serialize_instance
        return d