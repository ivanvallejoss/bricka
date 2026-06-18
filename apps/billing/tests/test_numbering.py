import pytest

from apps.billing.choices import DocumentType
from apps.billing.exceptions import UnmappedDocumentType
from apps.billing.numbering import assign_document_number

pytestmark = pytest.mark.django_db


class TestAssignDocumentNumber:
    def test_returns_increasing_numbers_for_same_type(self):
        first = assign_document_number(DocumentType.RENT_RECEIPT)
        second = assign_document_number(DocumentType.RENT_RECEIPT)
        assert second > first

    def test_sequences_are_independent_per_type(self):
        rent_before = assign_document_number(DocumentType.RENT_RECEIPT)
        assign_document_number(DocumentType.COMMISSION_RECEIPT)
        assign_document_number(DocumentType.COMMISSION_RECEIPT)
        rent_after = assign_document_number(DocumentType.RENT_RECEIPT)
        assert rent_after == rent_before + 1

    def test_owner_statement_has_its_own_sequence(self):
        # Regresión directa: esta sequence faltaba hasta la migración
        # que agregamos en esta sesión. Si alguien la borra, este test cae.
        number = assign_document_number(DocumentType.OWNER_STATEMENT)
        assert number >= 1

    def test_unmapped_type_fails_fast_with_clear_message(self):
        with pytest.raises(UnmappedDocumentType, match="sin sequence configurada"):
            assign_document_number("not_a_real_type")