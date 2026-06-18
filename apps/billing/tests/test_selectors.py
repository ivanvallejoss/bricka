from datetime import date

import pytest

from apps.billing.choices import DocumentStatus, DocumentType, PaymentStatus
from apps.billing.selectors import get_rental_payment_status
from apps.billing.tests.factories import BillingDocumentFactory
from apps.contracts.choices import ContractStatus
from apps.contracts.tests.factories import RentalContractFactory

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