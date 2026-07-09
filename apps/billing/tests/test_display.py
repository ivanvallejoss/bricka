import pytest

from apps.billing.choices import ConceptLineType, DocumentType
from apps.billing.display import enrich_lines_for_display, property_label
from apps.billing.tests.factories import BillingDocumentFactory
from apps.contracts.tests.factories import RentalContractFactory
from apps.deals.tests.factories import DealFactory

pytestmark = pytest.mark.django_db


class TestPropertyLabel:
    def test_property_label_prefers_contract_property(self):
        contract = RentalContractFactory()
        doc = BillingDocumentFactory(contract=contract)

        expected = contract.property.title or contract.property.address_line
        assert property_label(doc) == expected

    def test_property_label_uses_deal_listing_property(self):
        deal = DealFactory(with_listing=True)
        doc = BillingDocumentFactory(
            document_type=DocumentType.COMMISSION_RECEIPT,
            period=None,
            deal=deal,
        )

        expected = deal.listing.property.title or deal.listing.property.address_line
        assert property_label(doc) == expected

    def test_property_label_falls_back_to_external_notes(self):
        doc = BillingDocumentFactory(
            document_type=DocumentType.COMMISSION_RECEIPT,
            period=None,
            deal=DealFactory(),
        )

        assert property_label(doc) == "Propiedad externa — factory default"

    def test_property_label_empty_without_contract_or_deal(self):
        doc = BillingDocumentFactory()

        assert property_label(doc) == ""


class TestEnrichLines:
    def test_enrich_lines_marks_commission_subtractive_in_owner_statement(self):
        doc = BillingDocumentFactory(
            document_type=DocumentType.OWNER_STATEMENT,
            concept=[
                {"type": ConceptLineType.RENT, "description": "Alquiler", "amount": "500000"},
                {"type": ConceptLineType.COMMISSION, "description": "Honorarios", "amount": "40000"},
            ],
        )

        lines = enrich_lines_for_display(doc)

        assert lines[0]["is_subtractive"] is False
        assert lines[1]["is_subtractive"] is True

    def test_enrich_lines_commission_not_subtractive_in_receipt(self):
        doc = BillingDocumentFactory(
            document_type=DocumentType.COMMISSION_RECEIPT,
            period=None,
            deal=DealFactory(),
            concept=[
                {"type": ConceptLineType.COMMISSION, "description": "Honorarios", "amount": "40000"},
            ],
        )

        assert enrich_lines_for_display(doc)[0]["is_subtractive"] is False