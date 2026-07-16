from uuid import UUID
from dataclasses import dataclass
from decimal import Decimal

from apps.properties.models import Property

@dataclass
class BadgeContext:
    text: str
    style: str # success | warning | danger

@dataclass
class PropertyListContext:
    property: Property
    cover_url: str | None
    display_price: Decimal | None
    contextual_badge: BadgeContext | None = None

@dataclass
class MediaItemContext:
    id: UUID
    url: str
    is_cover: bool
    order: int