from decimal import Decimal

from django import forms

from apps.common.choices import Currency
from apps.listings.choices import OperationType
from .models import Property


class PropertyForm(forms.ModelForm):
    """
    Form escalar de edición de una propiedad (§2/§5).

    ModelForm SOLO como fuente de fields/widgets/validación derivada del
    modelo. REGLA: .save() no se llama nunca — update_property es la única
    puerta de escritura. La view mapea cleaned_data a kwargs EXPLÍCITOS
    (nunca **splat): location y externas no son de este form y deben quedar
    UNSET, o un guardado escalar borraría un pin o una fuente externa.

    Fuera del form a propósito: property_type/status/is_external (no
    editables), features (la view las junta por getlist), location/externas
    (S3b). El piso required (address_line/city/province) lo hereda del modelo
    (blank=False) — mismo piso que create_property, sin override.
    """

    # owner_contact_id NO es campo del modelo: el combobox reusable postea este
    # name y update_property lo consume. UUIDField como RentalContractForm —
    # valida formato, no existencia (el combobox postea ids válidos; la FK/DB
    # valida existencia). Vacío → None → owner se limpia (reemplazo, no UNSET).
    owner_contact_id = forms.UUIDField(required=False)

    class Meta:
        model = Property
        fields = [
            "title",
            "description",
            "address_line",
            "city",
            "province",
            "neighborhood",
            "area_m2",
            "bedrooms",
            "bathrooms",
            "parking_spaces",
            "year_built",
            "youtube_video_url",
        ]

    def clean(self):
        # Solo UX: no-negativos. Las reglas del dominio las valida
        # update_property; no se reimplementan acá (divergen). Vacíos: los
        # numéricos limpian a None y los texto a "" por derivación del tipo —
        # form y service acuerdan sin normalización manual.
        cleaned = super().clean()
        for field in ["area_m2", "bedrooms", "bathrooms", "parking_spaces", "year_built"]:
            value = cleaned.get(field)
            if value is not None and value < 0:
                self.add_error(field, "No puede ser un valor negativo.")
        return cleaned

class PropertyCreateForm(forms.ModelForm):
    """
    Fase 1 del wizard (§1): identificación. Crea el borrador vía
    create_property (.save() nunca). is_external es acá o nunca (prohibido en
    update_property). La regla is_external → agency_name la valida
    create_property; NO se duplica acá — la view captura el error como
    non-field (el toggle Alpine suma required advisory; el server es el juez).
    """
    # agency_name NO es campo de Property (vive en ExternalPropertySource);
    # declarado acá para la fase 1. required=False: el server valida la regla.
    agency_name = forms.CharField(required=False, max_length=200)

    class Meta:
        model = Property
        fields = [
            "property_type",
            "address_line",
            "city",
            "province",
            "neighborhood",
            "is_external",
        ]


class ListingCreateForm(forms.Form):
    """
    Alta de listing desde la sección Operación (§8-listing). Form PLANO:
    create_listing es la puerta (valida unicidad y crea el historial de precio).
    Este form solo valida tipos. operation_type se restringe a venta/alquiler
    (temporary_rent no se expone en V1); period NO es campo — la view lo deriva
    de operation_type (OPERATION_PERIOD). price_min_acceptable es opcional; su
    invariante (≤ price) es de dominio y su casa es create_listing, no este form.
    """
    operation_type = forms.ChoiceField(
        choices=[
            (OperationType.SALE.value, OperationType.SALE.label),
            (OperationType.RENT.value, OperationType.RENT.label),
        ],
    )
    price = forms.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.01"),
    )
    currency = forms.ChoiceField(
        choices=Currency.choices, initial=Currency.ARS,
    )
    price_min_acceptable = forms.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.01"),
        required=False,
    )


class ListingPriceForm(forms.Form):
    """Cambio de precio de un listing (§8-listing). update_listing_price es la
    puerta — escribe el historial en la misma transacción."""
    price = forms.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.01"),
    )