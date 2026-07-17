from django import forms

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
            "owner_contact",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner_contact"].empty_label = "Sin propietario"

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