from apps.contacts.tests.factories import ContactFactory
from apps.properties.forms import PropertyForm


def _data(**overrides):
    base = {
        "title": "",
        "description": "",
        "address_line": "Av. Siempreviva 742",
        "city": "Resistencia",
        "province": "Chaco",
        "neighborhood": "",
        "area_m2": "",
        "bedrooms": "",
        "bathrooms": "",
        "parking_spaces": "",
        "year_built": "",
        "youtube_video_url": "",
        "owner_contact": "",
    }
    base.update(overrides)
    return base


class TestPropertyForm:
    def test_valid_with_only_required(self, db):
        form = PropertyForm(data=_data())
        assert form.is_valid(), form.errors

    def test_requires_address_city_province(self, db):
        form = PropertyForm(data=_data(address_line="", city="", province=""))
        assert not form.is_valid()
        assert "address_line" in form.errors
        assert "city" in form.errors
        assert "province" in form.errors

    def test_empty_numerics_clean_to_none(self, db):
        form = PropertyForm(data=_data())
        assert form.is_valid(), form.errors
        assert form.cleaned_data["area_m2"] is None
        assert form.cleaned_data["bedrooms"] is None
        assert form.cleaned_data["year_built"] is None

    def test_empty_text_cleans_to_blank(self, db):
        form = PropertyForm(data=_data())
        assert form.is_valid(), form.errors
        assert form.cleaned_data["neighborhood"] == ""
        assert form.cleaned_data["youtube_video_url"] == ""

    def test_rejects_negative_numbers(self, db):
        form = PropertyForm(data=_data(bedrooms="-1"))
        assert not form.is_valid()
        assert "bedrooms" in form.errors

    def test_rejects_invalid_youtube_url(self, db):
        form = PropertyForm(data=_data(youtube_video_url="no-es-url"))
        assert not form.is_valid()
        assert "youtube_video_url" in form.errors

    def test_owner_contact_optional(self, db):
        form = PropertyForm(data=_data())
        assert form.is_valid(), form.errors
        assert form.cleaned_data["owner_contact"] is None

    def test_owner_contact_resolves(self, db):
        contact = ContactFactory()
        form = PropertyForm(data=_data(owner_contact=str(contact.pk)))
        assert form.is_valid(), form.errors
        assert form.cleaned_data["owner_contact"] == contact