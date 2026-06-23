from decimal import Decimal
from django import forms

from apps.common.choices import Currency
from .choices import AdjustmentIndex, GuaranteeType


class RentalContractForm(forms.Form):

    # Partes
    property_id = forms.UUIDField(
        error_messages={"required": "Seleccioná una propiedad."}
    )
    tenant_contact_id = forms.UUIDField(
        error_messages={"required": "Seleccioná un inquilino."}
    )
    owner_contact_id = forms.UUIDField(
        error_messages={"required": "Seleccioná un propietario."}
    )
    deal_id = forms.UUIDField(required=False)

    # Vigencia
    start_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))

    # Precio y pago
    initial_price = forms.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.01")
    )
    currency = forms.ChoiceField(choices=Currency.choices)
    payment_due_day = forms.IntegerField(min_value=1, max_value=28)
    late_fee_percent_daily = forms.DecimalField(
        max_digits=5, decimal_places=2, required=False
    )

    # Ajuste
    adjustment_index = forms.ChoiceField(choices=AdjustmentIndex.choices)
    adjustment_percent = forms.DecimalField(
        max_digits=5, decimal_places=2, required=False
    )
    adjustment_frequency_months = forms.IntegerField(min_value=1)

    # Garantía
    guarantee_type = forms.ChoiceField(choices=GuaranteeType.choices)
    deposit_amount = forms.DecimalField(
        max_digits=14, decimal_places=2, required=False
    )
    guarantee_detail = forms.CharField(required=False, widget=forms.Textarea)

    def clean_late_fee_percent_daily(self):
        value = self.cleaned_data.get("late_fee_percent_daily")
        return value if value is not None else Decimal("2.00")

    def clean(self):
        cleaned_data = super().clean()

        if (
            cleaned_data.get("adjustment_index") == AdjustmentIndex.FIXED_PERCENT
            and not cleaned_data.get("adjustment_percent")
        ):
            self.add_error(
                "adjustment_percent",
                "El porcentaje es requerido cuando el índice es porcentaje fijo."
            )

        start = cleaned_data.get("start_date")
        end = cleaned_data.get("end_date")
        if start and end and end <= start:
            self.add_error(
                "end_date",
                "La fecha de fin debe ser posterior a la fecha de inicio."
            )

        return cleaned_data