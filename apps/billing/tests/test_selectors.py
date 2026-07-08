from datetime import date

import pytest

from apps.billing.choices import DocumentStatus, DocumentType, PaymentStatus
from apps.billing.selectors import get_cobros, get_rental_payment_status
from apps.billing.tests.factories import BillingDocumentFactory
from apps.contracts.choices import ContractStatus
from apps.contracts.tests.factories import RentalContractFactory
from apps.deals.choices import DealType
from apps.deals.tests.factories import DealFactory

pytestmark = pytest.mark.django_db


class TestRentalPaymentStatus:
    def test_paid_when_issued_receipt_exists_for_period(self):
        contract = RentalContractFactory(status=ContractStatus.ACTIVE, payment_due_day=10)
        BillingDocumentFactory(
            document_type=DocumentType.RENT_RECEIPT,
            status=DocumentStatus.ISSUED,
            contract=contract,
            period=date(2026, 6, 1),
        )
        result = get_rental_payment_status([contract], as_of=date(2026, 6, 15))
        assert result[contract.id] == PaymentStatus.PAID

    def test_cancelled_receipt_does_not_count_as_paid(self):
        """El badge filtra status=ISSUED — una cancelación no debe
        mostrar falsamente 'Pago'."""
        contract = RentalContractFactory(status=ContractStatus.ACTIVE, payment_due_day=10)
        BillingDocumentFactory(
            document_type=DocumentType.RENT_RECEIPT,
            status=DocumentStatus.CANCELLED,
            contract=contract,
            period=date(2026, 6, 1),
        )
        result = get_rental_payment_status([contract], as_of=date(2026, 6, 15))
        assert result[contract.id] == PaymentStatus.OVERDUE

    def test_overdue_when_no_receipt_and_due_day_passed(self):
        contract = RentalContractFactory(status=ContractStatus.ACTIVE, payment_due_day=10)
        result = get_rental_payment_status([contract], as_of=date(2026, 6, 15))
        assert result[contract.id] == PaymentStatus.OVERDUE

    def test_pending_when_no_receipt_and_due_day_not_reached(self):
        contract = RentalContractFactory(status=ContractStatus.ACTIVE, payment_due_day=20)
        result = get_rental_payment_status([contract], as_of=date(2026, 6, 15))
        assert result[contract.id] == PaymentStatus.PENDING

    def test_non_active_contract_is_not_applicable(self):
        contract = RentalContractFactory(status=ContractStatus.SCHEDULED, payment_due_day=10)
        result = get_rental_payment_status([contract], as_of=date(2026, 6, 15))
        assert result[contract.id] == PaymentStatus.NOT_APPLICABLE

    def test_receipt_from_different_period_does_not_count(self):
        """Lectura A confirmada: el badge mira SOLO el mes corriente."""
        contract = RentalContractFactory(status=ContractStatus.ACTIVE, payment_due_day=10)
        BillingDocumentFactory(
            document_type=DocumentType.RENT_RECEIPT,
            status=DocumentStatus.ISSUED,
            contract=contract,
            period=date(2026, 5, 1),
        )
        result = get_rental_payment_status([contract], as_of=date(2026, 6, 15))
        assert result[contract.id] == PaymentStatus.OVERDUE

    def test_resolves_bulk_with_single_query(self, django_assert_num_queries):
        contracts = [
            RentalContractFactory(status=ContractStatus.ACTIVE, payment_due_day=10)
            for _ in range(5)
        ]
        with django_assert_num_queries(1):
            get_rental_payment_status(contracts, as_of=date(2026, 6, 15))

    def test_empty_input_returns_empty_dict(self):
        assert get_rental_payment_status([], as_of=date(2026, 6, 15)) == {}


class TestGetCobros:
    """Cobertura estrenada en S5 (b5) — get_cobros no tenía tests.
    Fija también el comportamiento preexistente (comisiones de venta,
    exclusión de rendiciones) que nunca se había pinneado.
    """

    def test_get_cobros_includes_rent_and_expense_receipts(self):
        rent = BillingDocumentFactory(document_type=DocumentType.RENT_RECEIPT)
        expense = BillingDocumentFactory(document_type=DocumentType.EXPENSE_RECEIPT)

        ids = {doc.pk for doc in get_cobros().object_list}

        assert rent.pk in ids
        assert expense.pk in ids

    def test_get_cobros_includes_sale_commission_receipts(self):
        doc = BillingDocumentFactory(
            document_type=DocumentType.COMMISSION_RECEIPT,
            period=None,
            deal=DealFactory(deal_type=DealType.SALE),
        )

        ids = {d.pk for d in get_cobros().object_list}

        assert doc.pk in ids

    def test_get_cobros_includes_rent_commission_receipts(self):
        """b5 (S5): la condición deal_type=SALE se eliminó — una comisión
        de alquiler es un cobro igual que una de venta. Cubre también el
        caso retroactivo: documentos emitidos ANTES del cambio aparecen
        porque es filtro de lectura, sin migración."""
        doc = BillingDocumentFactory(
            document_type=DocumentType.COMMISSION_RECEIPT,
            period=None,
            deal=DealFactory(deal_type=DealType.RENT),
        )

        ids = {d.pk for d in get_cobros().object_list}

        assert doc.pk in ids

    def test_get_cobros_excludes_owner_statements(self):
        doc = BillingDocumentFactory(
            document_type=DocumentType.OWNER_STATEMENT,
        )

        ids = {d.pk for d in get_cobros().object_list}

        assert doc.pk not in ids

    def test_get_cobros_period_filter_excludes_documents_without_period(self):
        """Gap #3 de seed-data.md, ACEPTADO como intencional: las comisiones
        no tienen period (son por operación, no periódicas) y bajo filtro
        de mes no aparecen. Si este test rompe, alguien cambió esa decisión —
        verificar que haya sido a propósito y actualizar seed-data.md."""
        from datetime import date as date_cls

        rent = BillingDocumentFactory(
            document_type=DocumentType.RENT_RECEIPT,
            period=date_cls(2026, 6, 1),
        )
        commission = BillingDocumentFactory(
            document_type=DocumentType.COMMISSION_RECEIPT,
            period=None,
            deal=DealFactory(deal_type=DealType.RENT),
        )

        ids = {d.pk for d in get_cobros(period=date_cls(2026, 6, 15)).object_list}

        assert rent.pk in ids
        assert commission.pk not in ids

    def test_get_cobros_search_matches_recipient_name(self):
        match = BillingDocumentFactory(
            document_type=DocumentType.RENT_RECEIPT,
            recipient_name="Carolina Ojeda",
        )
        no_match = BillingDocumentFactory(
            document_type=DocumentType.RENT_RECEIPT,
            recipient_name="Eduardo Maidana",
        )

        ids = {d.pk for d in get_cobros(search="carolina").object_list}

        assert match.pk in ids
        assert no_match.pk not in ids