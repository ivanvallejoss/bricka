from dataclasses import dataclass
from decimal import Decimal

from apps.properties.models import Property


@dataclass
class PropertyListContext:
    property: Property
    cover_url: str | None
    display_price: Decimal | None