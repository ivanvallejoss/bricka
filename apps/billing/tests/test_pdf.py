import pytest
from django.urls import reverse

from apps.billing.choices import DocumentStatus, DocumentType
from apps.billing.pdf import build_pdf_context, document_pdf_filename
from apps.billing.tests.factories import BillingDocumentFactory

pytestmark = pytest.mark.django_db


class TestDocumentPdfView:
    def test_document_pdf_returns_pdf_attachment(self, auth_client):
        doc = BillingDocumentFactory(document_type=DocumentType.RENT_RECEIPT)

        response = auth_client.get(reverse("billing:pdf", args=[doc.pk]))

        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert response.content[:5] == b"%PDF-"
        assert document_pdf_filename(doc) in response["Content-Disposition"]

    def test_document_pdf_404_when_document_does_not_exist(self, auth_client):
        url = reverse("billing:pdf", args=["00000000-0000-0000-0000-000000000000"])

        assert auth_client.get(url).status_code == 404


class TestBuildPdfContext:
    def test_build_pdf_context_marks_cancelled_document(self):
        doc = BillingDocumentFactory(status=DocumentStatus.CANCELLED)

        assert build_pdf_context(doc)["is_cancelled"] is True

    def test_build_pdf_context_owner_statement_uses_rendicion_label(self):
        doc = BillingDocumentFactory(document_type=DocumentType.OWNER_STATEMENT)

        ctx = build_pdf_context(doc)

        assert ctx["recipient_label"] == "Rendición a"

    def test_build_pdf_context_receipt_uses_recibido_label(self):
        doc = BillingDocumentFactory(document_type=DocumentType.RENT_RECEIPT)

        assert build_pdf_context(doc)["recipient_label"] == "Recibido de"

    def test_document_pdf_filename_uses_type_and_padded_number(self):
        doc = BillingDocumentFactory(document_type=DocumentType.RENT_RECEIPT)

        filename = document_pdf_filename(doc)

        assert filename.endswith(f"-{doc.number:04d}.pdf")
        assert " " not in filename