from django import forms
from django.contrib.auth import get_user_model

from .models import Contact
from .choices import ContactType, ContactRole, ContactSource, DocumentType

User = get_user_model()


class ContactForm(forms.ModelForm):
    assigned_agent = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        empty_label="Sin asignar",
    )

    class Meta:
        model = Contact
        fields = [
            "contact_type",
            "full_name",
            "email",
            "phone",
            "document_type",
            "document_number",
            "role",
            "source",
            "source_detail",
            "assigned_agent",
            "notes",
        ]

    def clean(self):
        cleaned_data = super().clean()
        document_type = cleaned_data.get("document_type")
        document_number = cleaned_data.get("document_number")

        if document_type and not document_number:
            self.add_error(
                "document_number",
                "Si especificás el tipo de documento, el número es obligatorio.",
            )
        if document_number and not document_type:
            self.add_error(
                "document_type",
                "Si especificás el número de documento, el tipo es obligatorio.",
            )
        return cleaned_data