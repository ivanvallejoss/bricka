from dataclasses import dataclass

from django.urls import reverse

from apps.listings.services import MIN_DESCRIPTION_LENGTH, MIN_PHOTOS_TO_PUBLISH
from apps.properties.models import Property


# Flujos que invocan el checklist. El link cambia según el flujo; el partial no.
FLOW_WIZARD = "wizard"
FLOW_EDIT = "edit"

# Orden de presentación canónico (matchea §1), independiente del orden en que
# el gate append-ea los códigos en missing.
_CANONICAL_ORDER = ("photos", "description")


@dataclass(frozen=True)
class PublicationChecklistItem:
    """Un requisito de publicación incumplido, ya resuelto para el template."""
    code: str              # código estable del gate ("photos" / "description")
    label: str             # "Fotos" / "Descripción"
    detail: str            # "3 de 5 mínimas" / "87/150 caracteres"
    link_url: str | None   # deep link a la superficie que lo corrige
    link_text: str | None  # "Ir a Fotos" / "Ir a Detalle"


def _photos_item(property: Property, flow: str) -> PublicationChecklistItem:
    if flow == FLOW_WIZARD:
        url = reverse("properties:new_fotos", args=[property.pk])
    else:
        url = reverse("properties:edit", args=[property.pk]) + "#fotos"
    return PublicationChecklistItem(
        code="photos",
        label="Fotos",
        detail=f"{property.media.count()} de {MIN_PHOTOS_TO_PUBLISH} mínimas",
        link_url=url,
        link_text="Ir a Fotos",
    )


def _description_item(property: Property, flow: str) -> PublicationChecklistItem:
    if flow == FLOW_WIZARD:
        url = reverse("properties:new_detalle", args=[property.pk])
    else:
        url = reverse("properties:edit", args=[property.pk]) + "#detalle"
    length = len(property.description.strip())
    return PublicationChecklistItem(
        code="description",
        label="Descripción",
        detail=f"{length}/{MIN_DESCRIPTION_LENGTH} caracteres",
        link_url=url,
        link_text="Ir a Detalle",
    )


_ITEM_BUILDERS = {
    "photos": _photos_item,
    "description": _description_item,
}


def build_publication_checklist(
    property: Property, missing: list[str], flow: str
) -> list[PublicationChecklistItem]:
    """
    Traduce ListingPublicationRequirementsError.missing a ítems renderables con
    deep link a la superficie que corrige cada requisito. Presentación única
    para todo rechazo del gate (§1): publicar desde el wizard, desde la edición,
    o reactivar (S4). El partial que los muestra es agnóstico al flujo.

    Un código desconocido (extensión futura del gate) NO se descarta en
    silencio: se degrada a un ítem sin deep link, para que el rechazo siga
    siendo visible aunque la UI todavía no sepa mapearlo.
    """
    missing_set = set(missing)
    items = [
        _ITEM_BUILDERS[code](property, flow)
        for code in _CANONICAL_ORDER
        if code in missing_set
    ]
    items.extend(
        PublicationChecklistItem(
            code=code,
            label="Requisito pendiente",
            detail=code,
            link_url=None,
            link_text=None,
        )
        for code in missing
        if code not in _ITEM_BUILDERS
    )
    return items